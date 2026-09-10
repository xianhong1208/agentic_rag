
"""Whisper 音檔防禦 — anti-hallucination patch、幻覺過濾、前導靜音裁切。

從 hierarchical_indexer.py 搬出(2026-07):這些是「讀檔」層的音訊前後處理,
與索引邏輯無關。indexing(hierarchical_indexer)與 REST STT(media router)
兩條路徑共用。

模組 import 時即套用 whisper anti-hallucination monkey-patch
(_enable_whisper_anti_hallucination_defaults,冪等)——必須早於
Docling AudioPipeline 首次 load whisper model。
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from src.log import get_api_logger

logger = get_api_logger()

# ---------------------------------------------------------------------------
# Whisper anti-hallucination defaults — monkey-patch whisper.load_model
# ---------------------------------------------------------------------------
# Docling 4.x's _NativeWhisperModel.transcribe calls model.transcribe(path,
# verbose=..., word_timestamps=...) with no other knobs — Whisper's built-in
# hallucination guards stay at their (overly permissive) defaults.
#
# Under AMD ROCm where flash/mem-efficient attention is experimental and numerical
# drift pushes some segments across no_speech threshold, the decoder falls into
# YouTube-outro / Buddhist-chant / song-credit hallucination loops on non-speech
# audio. NVIDIA shows the same mechanism with smaller blast radius.
#
# We patch whisper.load_model so every loaded model's transcribe() carries our
# tighter defaults:
#   - condition_on_previous_text=False:   each 30s decodes alone → no cascade
#   - no_speech_threshold=0.7:            > 0.6 default; more silence drop
#
# We DON'T hardcode language=zh — the trim below ensures Whisper sees real speech
# in its detection window, so auto-detect is reliable. Hardcoding zh would break
# non-Chinese audio someday.
# Idempotent. Fires once at module import, before Docling lazily instantiates the
# audio pipeline via get_converter().
# ---------------------------------------------------------------------------


def _enable_whisper_anti_hallucination_defaults() -> None:
    """Make every whisper.load_model() return a model whose transcribe() has
    anti-hallucination defaults baked in. Idempotent."""
    try:
        import whisper
    except ImportError:
        logger.info("whisper not installed; anti-hallucination patch skipped")
        return

    if getattr(whisper.load_model, "_anti_hallucination_wrapped", False):
        return

    _original_load = whisper.load_model
    _DEFAULTS = {
        "condition_on_previous_text": False,
        "no_speech_threshold": 0.7,
    }

    def _patched_load(*args, **kwargs):
        model = _original_load(*args, **kwargs)
        _original_transcribe = model.transcribe

        def _patched_transcribe(audio, **kw):
            for k, v in _DEFAULTS.items():
                kw.setdefault(k, v)
            return _original_transcribe(audio, **kw)

        model.transcribe = _patched_transcribe
        return model

    _patched_load._anti_hallucination_wrapped = True
    whisper.load_model = _patched_load
    logger.info(
        "Whisper anti-hallucination defaults enabled: "
        "condition_on_previous_text=False, no_speech_threshold=0.7"
    )


_enable_whisper_anti_hallucination_defaults()


# ---------------------------------------------------------------------------
# Audio pre-processing — trim leading silence before Whisper
# ---------------------------------------------------------------------------
# Why: Whisper auto-detects language on the first 30s mel spectrogram window.
# If those 30s are silent (e.g. meeting recording where host hasn't arrived),
# the encoder gets near-zero activations and language detection falls back to
# the highest-prior training language (English) — poisoning the whole transcript.
# Pre-trimming gives Whisper a real speech window for detection.
# Validated on 65min Taiwan presidential office mp3: en (36% confidence) → zh (99.8%).
# ---------------------------------------------------------------------------

_AUDIO_TRIM_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".opus", ".webm"}
_SILENCE_THRESHOLD_DB = -35.0
_SILENCE_MIN_DURATION = 2.0
_TRIM_SKIP_BELOW_SECONDS = 0.5  # don't bother re-encoding for <0.5s of leading silence

# Per-format encoder settings for trim re-encode. Defaults are reasonable quality
# for archival/transcription use cases (not music mastering). Unknown extensions
# fall back to `-c:a copy` which is fastest + lossless but only works if ffmpeg
# can seek precisely (most modern containers can).
_TRIM_CODEC_ARGS: dict[str, list[str]] = {
    ".mp3":  ["-c:a", "libmp3lame", "-q:a", "2"],
    ".wav":  ["-c:a", "pcm_s16le"],
    ".m4a":  ["-c:a", "aac", "-b:a", "192k"],
    ".aac":  ["-c:a", "aac", "-b:a", "192k"],
    ".flac": ["-c:a", "flac"],
    ".ogg":  ["-c:a", "libvorbis"],
    ".opus": ["-c:a", "libopus"],
}


# Whisper hallucination patterns — Chinese training data leakage from YouTube.
# Triggered when Whisper sees non-speech audio (intro music, chimes, silence) and falls
# back to high-prior token sequences. Validated on 2026-05-21 presidential meeting mp3:
# 1 song-credit + 9x "明镜与点点" outro at the start (before "各位貴賓請就座").
# Only applied to audio files (.wav/.mp3); these rarely appear in legitimate transcripts
# but applying broadly could false-positive on quoted content in PDFs.
_WHISPER_HALLUCINATION_PATTERNS = [
    # Song credits — "詞・作曲・編曲 李宗盛" pattern (Whisper thinks it's a music video intro)
    re.compile(r"[词詞][・·•\s]{0,3}作曲[・·•\s]{0,3}[编編]曲\s*[一-鿿]{0,15}"),
    # "明镜与点点" YouTube channel outro — `+` matches consecutive repeats as one block
    re.compile(
        r"(?:[请請]不吝[点點][赞讚][^。\n]{0,40}?明[镜鏡][与與][点點][点點][^。\n]{0,15}?[栏欄]目[\s,、。]*)+"
    ),
    # Generic subscribe/donate outros
    re.compile(r"打[赏賞]支持[^。\n]{0,20}?[栏欄]目[\s,、。]*"),
    re.compile(r"[请請][订訂][阅閱][^。\n]{0,20}?(?:[频頻][道台]|频道)[\s,、。]*"),
    re.compile(r"[感][谢謝][观觀]看[本这這的][^。\n]{0,15}"),
    # Fan-subbing credits
    re.compile(r"字幕由[^。\n]{0,30}?Amara[^。\n]{0,30}"),
    re.compile(r"由志[愿願]者[^。\n]{0,15}?[提組]供"),
    re.compile(r"字幕志[愿願]者[^。\n]{0,30}"),
]


# Generic "same phrase repeats N+ times in a row" detector. Whisper repetition
# hallucinations (e.g., "請回座 請回座 請回座 ..." with zero-duration timestamps when
# the model gets stuck in a token loop) don't need an explicit pattern — they show up
# as consecutive duplicates of a 3-30 char Chinese phrase separated by whitespace/CJK
# punctuation. Validated on 2026-05-21 meeting mp3: "請回座" × 7 consecutive copies.
_REPETITION_PATTERN = re.compile(
    r"([一-鿿]{3,30})"        # phrase: 3-30 Chinese chars
    r"(?:[\s,，。、!?！?]*\1){2,}"      # plus ≥ 2 more identical copies → total ≥ 3
)


def _strip_consecutive_repetitions(text: str) -> tuple[str, int]:
    """把連續重複 3+ 次的同一段 3-30 字中文片段收成 1 份(Whisper repetition 幻覺處理)。

    Args:
        text: 原始文字。

    Returns:
        ``(cleaned, n_excess_copies_removed)`` ─ cleaned 為收斂後文字。"""
    if not text:
        return text, 0
    removed = 0

    def _collapse(m: "re.Match[str]") -> str:
        nonlocal removed
        phrase = m.group(1)
        # rough copy count from match span — phrase + separators repeat
        n_copies = m.group(0).count(phrase)
        removed += max(0, n_copies - 1)
        return phrase

    cleaned = _REPETITION_PATTERN.sub(_collapse, text)
    return cleaned, removed


def _filter_whisper_hallucinations(text: str) -> tuple[str, int]:
    """雙層過濾 Whisper 幻覺:已知 regex pattern + 通用連續重複 detector。

    Args:
        text: 原始 Whisper 輸出。

    Returns:
        ``(cleaned, n_stripped)`` ─ n_stripped 為總共拿掉的 match 數量。"""
    if not text:
        return text, 0
    total = 0
    # Layer 1: known patterns
    for pat in _WHISPER_HALLUCINATION_PATTERNS:
        text, n = pat.subn("", text)
        total += n
    # Layer 2: generic repetition (catches '請回座 請回座 ...' without enumerating phrases)
    text, n = _strip_consecutive_repetitions(text)
    total += n
    return text, total


def _detect_leading_silence_end(src: str) -> float:
    """用 ffmpeg silencedetect 偵測開頭靜音結束時間(秒)。

    只抓「真的靜音」;前奏音樂 / 鐘聲等非語音由下游 Whisper 輸出階段的
    _strip_consecutive_repetitions 處理。

    Args:
        src: 音檔路徑。

    Returns:
        靜音結束時間(秒);沒明顯開頭靜音回 0.0。
    """
    af = f"silencedetect=noise={_SILENCE_THRESHOLD_DB}dB:duration={_SILENCE_MIN_DURATION}"
    cmd = ["ffmpeg", "-hide_banner", "-i", src, "-vn", "-af", af, "-f", "null", "-"]
    result = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    starts = re.findall(r"silence_start:\s*([\d.]+)", result.stderr)
    ends = re.findall(r"silence_end:\s*([\d.]+)", result.stderr)
    if not starts or not ends or float(starts[0]) > 1.0:
        return 0.0
    return float(ends[0])


def _trim_audio_leading_silence(input_path: str, file_name: str) -> Optional[str]:
    """去掉音檔開頭靜音,回 temp 檔路徑(沒靜音時回 None)。

    走 silencedetect 抓 timestamp + `-ss` seek + re-encode(ffmpeg 4.x 的 silenceremove
    對長檔不可靠)。**caller 用完務必 `unlink()`**。

    Args:
        input_path: 原音檔路徑。
        file_name: 顯示用檔名(log + 副檔名推測)。

    Returns:
        temp 檔路徑(已 trim);沒靜音時 None。

    Raises:
        RuntimeError: ffmpeg 失敗。
    """
    seek_ts = _detect_leading_silence_end(input_path)
    detector = "ffmpeg silencedetect"

    if seek_ts <= _TRIM_SKIP_BELOW_SECONDS:
        return None

    suffix = Path(file_name).suffix.lower() or ".mp3"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.close()
    out_path = tmp.name

    # Unknown suffix → -c:a copy(fastest, lossless,大部分容器 ffmpeg 可以 keyframe-align seek)
    codec_args = _TRIM_CODEC_ARGS.get(suffix, ["-c:a", "copy"])

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", str(seek_ts),
        "-i", input_path, "-vn",
        *codec_args,
        out_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if result.returncode != 0:
        Path(out_path).unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg seek-trim failed: {result.stderr[:500]}")

    logger.info(
        f"Trimmed leading non-speech: {file_name} -- skipped first {seek_ts:.1f}s "
        f"via {detector} before Whisper transcription"
    )
    return out_path

