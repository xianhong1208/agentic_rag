
"""FireRedASR-AED-L 本地 provider(BL-08)。

工程約束(模型卡與上游 issue 實證):
- **60s 輸入硬上限**:>60s 開始幻覺、>200s 位置編碼越界 → 先用 ffmpeg
  silencedetect 找靜音點,貪婪切成 ≤55s 段(留 5s 安全邊);整段無靜音
  時硬切 55s。
- **16kHz mono**:ffmpeg 統一重採樣(任何來源格式 → pcm_s16le wav)。
- **輸出簡體**:AED 訓練語料為簡中 → OpenCC `s2twp`(簡→繁+台灣用語)
  後處理,繁中驗收由 evals 的簡體字比率把關。
- **AED 無標點**:輸出交 leaf_splitter 純文字路徑(chunks=None)。

程式碼來源:vendor/fireredasr_src(官方 FireRedTeam/FireRedASR,Apache-2.0,
無 PyPI 發佈故 vendor;以 uv path dependency 裝進 site-packages,Nuitka
打包時隨依賴編進 binary — 部署不需外帶 vendor/;見該目錄 README)。
權重:assets/fireredasr/FireRedASR-AED-L/(~4.7GB,不進 repo,要外帶)。

模型載入為 lazy singleton(首次 transcribe 才載,與 docling converter 同
模式);推論鎖序列化 — 1.1B 模型並發 forward 會 OOM。
"""

from __future__ import annotations

import re
import subprocess
import threading
import wave
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from src.log import get_api_logger
from src.domain.rag.asr_base import AsrProvider, AsrResult

logger = get_api_logger()

# 60s 硬上限留 5s 安全邊(模型卡:>60s 幻覺、>200s 位置編碼越界)
MAX_SEGMENT_SECONDS = 55.0
# silencedetect 參數:-35dB 以下持續 0.3s 視為靜音(會議語音的自然停頓)
_SILENCE_FILTER = "silencedetect=noise=-35dB:d=0.3"

_model_lock = threading.Lock()
_model = None  # lazy singleton: (FireRedAsr, use_gpu)
# 推論鎖:索引路徑(document_loader)與 media 的 /v1/transcriptions 共用同
# 一顆 1.1B 模型 instance,並發 forward 會 KV-cache race / OOM(與 docling
# 的 DOCLING_INFER_LOCK 同理)。所有 model.transcribe 都必須在這把鎖內。
FIRERED_INFER_LOCK = threading.Lock()


def _resolve_model_dir() -> Optional[Path]:
    """權重目錄:assets/fireredasr/FireRedASR-AED-L(model.pth.tar 在才算就緒)。"""
    from src.domain.rag.docling_loader import resolve_assets_dir
    assets = resolve_assets_dir()
    if assets is None:
        return None
    d = assets / "fireredasr" / "FireRedASR-AED-L"
    return d if (d / "model.pth.tar").is_file() else None


def _load_model(model_dir: Path):
    """載入 AED 模型(singleton;fireredasr 為已安裝套件,正常 import)。"""
    global _model
    with _model_lock:
        if _model is not None:
            return _model
        import torch
        # fireredasr = uv path dependency(vendor/fireredasr_src 裝進
        # site-packages)→ 正常 import,Nuitka 打包時當一般依賴編進 binary,
        # 部署不需外帶 vendor/。缺套件時給可行動錯誤(而非裸 ImportError)。
        try:
            from fireredasr.models.fireredasr import FireRedAsr
        except ImportError as e:
            raise RuntimeError(
                "fireredasr 套件不可 import — 開發環境跑 `uv sync --group <gpu>`"
                "(path dep 指向 vendor/fireredasr_src);打包環境確認 Nuitka 有"
                "收錄 fireredasr(必要時加 --include-package=fireredasr)"
            ) from e

        use_gpu = torch.cuda.is_available()
        logger.info(f"[FIREREDASR] loading AED-L from {model_dir} (gpu={use_gpu})")
        # torch 2.6+ 預設 weights_only=True,官方 checkpoint 的 "args" 是
        # argparse.Namespace → 需白名單放行(僅此類;其餘反序列化保護不變,
        # 也不改 vendor 程式碼)
        import argparse
        with torch.serialization.safe_globals([argparse.Namespace]):
            model = FireRedAsr.from_pretrained("aed", str(model_dir))
        _model = (model, use_gpu)
        logger.info("[FIREREDASR] model ready")
        return _model


# ---------------------------------------------------------------------------
# 切段規劃(純函式,可單測)
# ---------------------------------------------------------------------------

def parse_silences(ffmpeg_stderr: str) -> List[Tuple[float, float]]:
    """從 ffmpeg silencedetect stderr 抽 (silence_start, silence_end) 對。

    末段 silence 可能只有 start(檔案在靜音中結束)— 丟棄不完整對即可,
    切段規劃只需要「檔案中間」的靜音。
    """
    starts = [float(m) for m in re.findall(r"silence_start:\s*([\d.]+)", ffmpeg_stderr)]
    ends = [float(m) for m in re.findall(r"silence_end:\s*([\d.]+)", ffmpeg_stderr)]
    return list(zip(starts, ends))


def plan_segments(
    duration: float,
    silences: List[Tuple[float, float]],
    max_seg: float = MAX_SEGMENT_SECONDS,
) -> List[Tuple[float, float]]:
    """貪婪切段:每段 ≤ max_seg,切點取「窗內最後一個靜音的中點」。

    - duration ≤ max_seg → 單段
    - 窗內無靜音 → 硬切 max_seg(寧可切在字中間,也不能餵 >60s 產生幻覺)
    - 靜音中點 = 停頓中央,兩側語音都完整
    """
    if duration <= max_seg:
        return [(0.0, duration)]
    cuts = sorted((s + e) / 2.0 for s, e in silences)
    segments: List[Tuple[float, float]] = []
    start = 0.0
    while duration - start > max_seg:
        window_end = start + max_seg
        candidates = [c for c in cuts if start < c <= window_end]
        cut = candidates[-1] if candidates else window_end
        segments.append((start, cut))
        start = cut
    segments.append((start, duration))
    return segments


# ---------------------------------------------------------------------------
# 音訊前處理(ffmpeg)
# ---------------------------------------------------------------------------

def _resample_to_wav16k(src: str, dst: Path) -> None:
    proc = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-i", src,
         "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst)],
        capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 重採樣失敗: {proc.stderr[-500:]}")


def _detect_silences(wav_path: Path) -> List[Tuple[float, float]]:
    proc = subprocess.run(
        ["ffmpeg", "-nostdin", "-i", str(wav_path),
         "-af", _SILENCE_FILTER, "-f", "null", "-"],
        capture_output=True, text=True, timeout=600,
    )
    # silencedetect 寫 stderr;非零退出也照 parse(空清單 → 硬切,不擋轉錄)
    return parse_silences(proc.stderr)


def _slice_wav(wav_path: Path, segments: List[Tuple[float, float]], out_dir: Path) -> List[Path]:
    """stdlib wave 切段(16k mono pcm16,一次讀入切 N 份,比 N 次 ffmpeg 快)。"""
    paths: List[Path] = []
    with wave.open(str(wav_path), "rb") as w:
        rate = w.getframerate()
        params = w.getparams()
        frames = w.readframes(w.getnframes())
    width = params.sampwidth  # pcm_s16le → 2
    for i, (start, end) in enumerate(segments):
        lo = int(start * rate) * width
        hi = int(end * rate) * width
        p = out_dir / f"seg_{i:04d}.wav"
        with wave.open(str(p), "wb") as out:
            out.setparams(params)
            out.writeframes(frames[lo:hi])
        paths.append(p)
    return paths


class FireRedAsrProvider(AsrProvider):
    """本地 FireRedASR-AED-L(切段 → 逐段推論 → 拼接 → s2twp 繁化)。"""

    def __init__(self, *, beam_size: int = 3):
        self._beam_size = beam_size
        self._s2twp = None  # lazy(opencc 載字典)

    def available(self) -> bool:
        return _resolve_model_dir() is not None

    def _to_traditional(self, text: str) -> str:
        if self._s2twp is None:
            import opencc
            self._s2twp = opencc.OpenCC("s2twp")
        return self._s2twp.convert(text)

    def _transcribe_segments(self, seg_paths: List[Path]) -> List[str]:
        """逐段推論(不 batch:段長已近上限,batch pad 只會浪費;OOM 風險低)。"""
        model_dir = _resolve_model_dir()
        if model_dir is None:  # available() 守過,這裡是二次防禦
            raise RuntimeError("FireRedASR 權重不在 assets/fireredasr/FireRedASR-AED-L")
        model, use_gpu = _load_model(model_dir)
        texts: List[str] = []
        for p in seg_paths:
            with FIRERED_INFER_LOCK:  # 索引與 media STT 共用模型,序列化推論
                results = model.transcribe(
                    [p.stem], [str(p)],
                    {"use_gpu": use_gpu, "beam_size": self._beam_size, "nbest": 1},
                )
            texts.append(results[0]["text"].strip() if results else "")
        return texts

    def transcribe(
        self, *, audio_path: str, file_name: str,
        max_tokens: Optional[int] = None, tokenizer: Optional[str] = None,
        progress_cb: Optional[Callable] = None,
    ) -> AsrResult:
        import tempfile

        with tempfile.TemporaryDirectory(prefix="fireredasr_") as td:
            tdir = Path(td)
            wav = tdir / "input16k.wav"
            _resample_to_wav16k(audio_path, wav)
            with wave.open(str(wav), "rb") as w:
                duration = w.getnframes() / w.getframerate()

            segments = plan_segments(duration, _detect_silences(wav))
            seg_paths = _slice_wav(wav, segments, tdir)
            logger.info(
                f"[FIREREDASR] {file_name}: {duration:.1f}s → {len(segments)} segment(s)"
            )

            texts = []
            for i, sp in enumerate(self._transcribe_segments(seg_paths)):
                texts.append(sp)
                if progress_cb is not None:
                    try:
                        progress_cb("loading", i + 1, len(seg_paths))
                    except Exception:
                        pass

        full = self._to_traditional("\n".join(t for t in texts if t))
        return AsrResult(text=full, chunks=None)
