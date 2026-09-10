
"""Media REST API — STT / OCR via Docling's pre-loaded models.

直接呼叫 docling 的 singleton DocumentConverter,共用 hierarchical_indexer 已 load
的 Whisper turbo (ASR) + RapidOCR (PDF/Image OCR) 模型。不額外載入,不 proxy 外部
container。

Endpoints:
- POST /v1/transcriptions/general  — audio → text(後端跟隨 rag.asr.provider)
- POST /v1/ocr/general             — image/pdf → text (Docling OCR pipeline)
- GET  /v1/models                  — 列出已 load 的模型
"""
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse

from src.api.router.response import ErrorDetailResponse
from src.domain.rag.docling_loader import get_converter, DOCLING_INFER_LOCK
from src.domain.rag.audio_defense import (
    _AUDIO_TRIM_EXTENSIONS,
    _filter_whisper_hallucinations,
    _trim_audio_leading_silence,
)
from src.log import get_api_logger

logger = get_api_logger()

# PyTorch transformer 模型不是 thread-safe — 同一個 model instance 並發兩個 transcribe()
# 會觸發 "cannot reshape tensor of 0 elements" 之類的 KV-cache race。
# 單 GPU 本來就無法並行兩個 forward,serialize 也不損吞吐量。
# STT / OCR 模型不同,獨立 lock 不互鎖。
_WHISPER_INFER_LOCK = threading.Lock()
# H2: docling converter 是全 process 單例,索引路徑也會 convert 它。改用
# docling_loader 的同一把推論鎖,讓「索引」與「/v1/ocr、/v1/transcriptions」
# 之間也序列化,否則同一 instance 並發 forward 會 CUDA crash / OOM。
_DOCLING_INFER_LOCK = DOCLING_INFER_LOCK

# ⚠️ 刻意不掛認證(2026-07 決策):STT/OCR 的呼叫端拿不到 token,豁免 auth、
# 只留 100MB 上傳上限擋濫用。代價是匿名端可驅動 Whisper/OCR GPU 推論 —
# 僅適用於內網部署;要重新上鎖,加回 dependencies=[Depends(authenticate_request)]
router = APIRouter(
    tags=["Media"],
    prefix="/v1",
)


_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".opus", ".webm"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".gif", ".webp", ".pdf"}

# 上傳大小上限 — 對齊 FileDB.MAX_FILE_SIZE(100MB)。UploadFile 是串流寫入
# temp file,沒有上限的話單一 request 就能塞爆 temp disk
_MAX_UPLOAD_BYTES = 100 * 1024 * 1024


def _get_config_asr_provider():
    """media STT 的語音來源 = config `rag.asr.provider`,與索引同一個 —
    設定一處、所有語音任務生效。

    - docling-whisper(或 config 缺省)→ 回 (None, None):走原 whisper-direct
      路徑(**同一個** config 選定的模型,只是直呼以保留 language/prompt 控制)
    - fireredasr / openai-compatible → 回 (provider, name);**不可用時由呼叫端
      回 503**,絕不靜默改用別的模型(config 選了誰就是誰)
    - 非 whisper provider 不支援 language/prompt(FireRedASR 為中英 AED、無
      prompt bias)— 端點收到會記 log 並忽略
    """
    try:
        from src.config.config_manager import Config as _Cfg
        asr_cfg = getattr(getattr(_Cfg.get_config_model(), "rag", None), "asr", None)
    except Exception:
        asr_cfg = None  # config 讀不到 → 視同缺省(docling-whisper 舊語義)
    if asr_cfg is None or not asr_cfg.enabled or asr_cfg.provider == "docling-whisper":
        return None, None
    from src.domain.rag.asr_provider import create_asr_provider
    return create_asr_provider(asr_cfg), asr_cfg.provider


def _get_loaded_whisper():
    """從 docling 已初始化的 AsrPipeline 抓出底層 whisper.Whisper instance。

    docling 的 _NativeWhisperModel.transcribe() 沒把 options 裡的 `language` 傳給
    whisper(忽略掉),也沒暴露 `initial_prompt`。直接拿 raw whisper model 自己呼叫
    才能完整控制這些參數。

    Returns whisper model instance (with `.transcribe(audio, language=..., initial_prompt=...)`),
    or None if AsrPipeline 還沒 warm。
    """
    converter = get_converter()
    pipes = getattr(converter, "initialized_pipelines", {}) or {}
    for (klass, _hash), pipe in pipes.items():
        if klass.__name__ == "AsrPipeline":
            inner = getattr(pipe, "_model", None)
            return getattr(inner, "model", None)
    return None


async def _save_upload_to_temp(file: UploadFile) -> tuple[str, int]:
    """串流寫入 temp file,避免一次把整個 audio 載入記憶體。

    Args:
        file: FastAPI UploadFile 物件。

    Returns:
        ``(temp_path, bytes_written)`` ─ caller 用完務必 unlink。
    """
    suffix = Path(file.filename or "upload").suffix.lower() or ".bin"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    bytes_written = 0
    try:
        while chunk := await file.read(1 << 20):  # 1MB
            bytes_written += len(chunk)
            if bytes_written > _MAX_UPLOAD_BYTES:
                tmp.close()
                Path(tmp.name).unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"Upload exceeds {_MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit"
                    ),
                )
            tmp.write(chunk)
    except BaseException:
        # 失敗路徑(含 client 斷線的 CancelledError、413)清掉半成品 temp,
        # 別留在磁碟。成功路徑不 unlink —— caller 要用 tmp.name。
        tmp.close()
        Path(tmp.name).unlink(missing_ok=True)
        raise
    finally:
        tmp.close()
    return tmp.name, bytes_written


def _unlink_safe(path: Optional[str]) -> None:
    if path:
        Path(path).unlink(missing_ok=True)


# Extensions where docling's format dispatcher reliably routes to the
# AudioPipeline。 Everything else (.webm,future containers) gets
# transcoded to .wav first ─ see _transcode_to_wav 的 docstring 細節。
_DOCLING_AUDIO_SAFE_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus"}


def _transcode_to_wav(input_path: str) -> str:
    """Transcode an audio file to 16 kHz mono WAV via ffmpeg。

    Why this exists:
        docling's format dispatcher runs a three-stage waterfall ─
        ``filetype.guess_mime`` (magic bytes) → extension lookup →
        content sniff ─ and the magic-byte stage is *content*-driven,
        not extension-driven。 We previously tried to renaming
        ``.webm`` to ``.ogg`` thinking docling keyed off the suffix,
        but the magic-byte stage saw the EBML/Matroska header
        (``1A 45 DF A3``) and tagged the file as webm regardless of
        the renamed extension。 docling has no webm → audio mapping,
        so the dispatcher returned ``None`` and the convert call
        failed before AudioPipeline could ever see it。

        Stop fighting the dispatcher。 Run a tiny ffmpeg pass that
        re-packages whatever container the browser sent (typically
        webm/opus on Chrome,mp4/aac on Safari) into a plain
        ``RIFF....WAVE`` PCM-16 WAV at 16 kHz mono。 docling's first
        waterfall stage recognises WAV by magic bytes,routes to
        AudioPipeline,Whisper runs。 Same downstream pipeline that
        already works for ``.wav`` uploads。

    Performance:
        For a 60-second browser recording (~100 KB opus,~1.9 MB
        as wav at 16k mono) the transcode runs in ~150 ms on a
        modern CPU ─ negligible compared to the 1-3 second Whisper
        inference that follows。 The wav is bigger on disk but
        nobody keeps it ─ the caller unlinks it after the response。

    Args:
        input_path: Source audio path。 ffmpeg auto-detects the
            container from content, so the extension can be wrong
            or missing。

    Returns:
        Path to a new ``.wav`` temp file。 Caller owns it (unlink
        when done)。

    Raises:
        RuntimeError: ffmpeg failure。 Caller should surface this
            as a 502 so the FE knows to retry。
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    out_path = tmp.name
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", input_path,
        "-vn",          # belt-and-braces:browser blobs are audio-only,
                        # but a stray cover-art image inside a webm/mp4
                        # would otherwise become a video stream and break
                        # the WAV output。 The ffmpeg `-vn` flag matches
                        # the audio-pipeline gotcha we hit on YouTube
                        # downloads ─ keeping it here as a deliberate
                        # invariant。
        "-ar", "16000",  # Whisper's native sample rate ─ saves an internal
                         # resample step。
        "-ac", "1",      # Mono。 Browser mic captures are nearly always
                         # mono already;forcing it here avoids a
                         # downstream stereo-to-mono fold for the rare
                         # multi-channel input。
        "-f", "wav",
        out_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if result.returncode != 0:
        Path(out_path).unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg transcode failed: {result.stderr[:500]}")
    return out_path


def _fmt_size(n: int) -> str:
    """Human-friendly byte size:1234 → '1.2 KB'。"""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024  # type: ignore
    return f"{n:.1f} TB"


# Response = json (預設) 含 {text, language, duration, segments[]} 或 plain text (response_format=text)
@router.post(
    "/transcriptions/general",
    summary="Audio → text(跟隨 rag.asr.provider)",
    description="OpenAI-compatible-ish 多媒體 STT 端點。後端跟隨 config rag.asr.provider:docling-whisper(共用已 load 的 Whisper turbo,支援 language/prompt)或 fireredasr / openai-compatible(與索引同一 AsrProvider;language/prompt 忽略)。",
    responses={
        200: {
            "description": "json: {text, language, duration, segments} / text: plain transcript",
            "content": {
                "application/json": {"example": {"text": "今天天氣很好。", "language": "zh", "duration": 12.3}},
                "text/plain": {"example": "今天天氣很好。"},
            },
        },
        415: {"model": ErrorDetailResponse, "description": "不支援的音檔格式"},
        500: {"model": ErrorDetailResponse, "description": "Whisper 推論失敗"},
    },
)
async def transcribe(
    audio: UploadFile = File(...),
    language: Optional[str] = Form(None),
    prompt: Optional[str] = Form(None),
    response_format: str = Form("json"),
    trim_leading_silence: bool = Form(True),
    strip_hallucinations: bool = Form(True),
):
    """Args:
        audio:                 音檔(mp3 / wav / m4a / flac / ogg / aac / opus)— 對齊 mistt 欄位名
        language:              ISO-639-1 語言碼(例:'zh' / 'en' / 'ja');None = Whisper 自動偵測
        prompt:                上下文提示給 Whisper(專有名詞 / 領域術語 bias),預設 None
        response_format:       json | text(預設 json)
        trim_leading_silence:  是否先用 ffmpeg silencedetect 砍掉開頭沉默(預設 True)
        strip_hallucinations:  是否套 Whisper 幻覺過濾 + 重複收斂(預設 True)
    """
    t_start = time.time()
    file_name = audio.filename or "audio"
    ext = Path(file_name).suffix.lower()
    logger.info(
        f"[transcribe] ⮕ request received | file={file_name} ext={ext} "
        f"content_type={audio.content_type} "
        f"lang={language or 'auto'} prompt={'set' if prompt else 'none'} "
        f"trim={trim_leading_silence} strip_hallucinations={strip_hallucinations} "
        f"response_format={response_format}"
    )
    if ext not in _AUDIO_EXTS:
        logger.warning(f"[transcribe] ✗ rejected unsupported ext={ext} for {file_name}")
        raise HTTPException(415, f"Unsupported audio format: {ext}. Allowed: {sorted(_AUDIO_EXTS)}")

    t_save = time.time()
    src_path, bytes_written = await _save_upload_to_temp(audio)
    save_elapsed = time.time() - t_save
    logger.info(
        f"[transcribe] · upload saved | size={_fmt_size(bytes_written)} "
        f"tmp={src_path} save_elapsed={save_elapsed:.2f}s"
    )

    trimmed_path: Optional[str] = None
    transcoded_path: Optional[str] = None
    effective_path = src_path
    try:
        # ── Transcode-to-wav for docling-unfriendly containers ──
        # Browser MediaRecorder produces ``.webm`` on Chrome / Edge ─
        # docling's format dispatcher (magic-byte first stage) tags
        # the bytes as webm and has no webm → audio mapping。 When
        # whisper-direct is unavailable the request falls back to
        # docling-asr,which then rejects the file。 The fix is to
        # re-package the audio into a plain WAV (PCM-16 16 kHz mono)
        # via ffmpeg before any downstream step ─ both whisper-direct
        # and docling-asr accept WAV unconditionally。 We only do this
        # for the docling-unfriendly extensions to keep the happy
        # path (``.mp3`` / ``.wav`` etc.) at zero overhead。
        if ext not in _DOCLING_AUDIO_SAFE_EXTS:
            t_transcode = time.time()
            try:
                transcoded_path = await run_in_threadpool(_transcode_to_wav, src_path)
                effective_path = transcoded_path
                logger.info(
                    f"[transcribe] · transcoded → wav | "
                    f"new={transcoded_path} elapsed={time.time() - t_transcode:.2f}s"
                )
            except Exception as e:
                logger.error(
                    f"[transcribe] ✗ transcode failed for {file_name}: {e}"
                )
                raise HTTPException(
                    status_code=502,
                    detail=f"Audio transcode failed: {e}",
                )

        if trim_leading_silence and ext in _AUDIO_TRIM_EXTENSIONS:
            t_trim = time.time()
            try:
                trimmed_path = await run_in_threadpool(
                    _trim_audio_leading_silence, src_path, file_name
                )
                trim_elapsed = time.time() - t_trim
                if trimmed_path:
                    effective_path = trimmed_path
                    logger.info(
                        f"[transcribe] · leading silence trimmed | "
                        f"new={trimmed_path} elapsed={trim_elapsed:.2f}s"
                    )
                else:
                    logger.info(
                        f"[transcribe] · no leading silence to trim "
                        f"(elapsed={trim_elapsed:.2f}s)"
                    )
            except Exception as e:
                trim_elapsed = time.time() - t_trim
                logger.warning(
                    f"[transcribe] ⚠ trim failed for {file_name} "
                    f"(elapsed={trim_elapsed:.2f}s,使用原始檔): {e}"
                )

        cfg_provider, cfg_provider_name = _get_config_asr_provider()
        whisper_model = None if cfg_provider is not None else _get_loaded_whisper()
        if cfg_provider is not None:
            if not cfg_provider.available():
                # config 選定的模型不可用 → 明確 503,不偷換別的模型
                logger.error(
                    f"[transcribe] ✗ configured provider {cfg_provider_name} unavailable "
                    "(weights/endpoint not ready)"
                )
                raise HTTPException(
                    503,
                    f"rag.asr.provider={cfg_provider_name} 不可用(權重/端點未就緒)— "
                    "檢查 assets/ 權重或 rag.asr 設定",
                )
            backend = f"asr-provider:{cfg_provider_name}"
            if language or prompt:
                logger.info(
                    f"[transcribe] · language/prompt 參數對 {cfg_provider_name} 不適用,忽略"
                )
        else:
            backend = "whisper-direct" if whisper_model is not None else "docling-asr"
        queued = _WHISPER_INFER_LOCK.locked()
        if queued:
            logger.info(
                f"[transcribe] · inference queued | backend={backend} "
                f"(another request holds whisper lock)"
            )
        else:
            logger.info(f"[transcribe] · inference start | backend={backend}")
        t_lock_request = time.time()

        if cfg_provider is not None:
            # config 指定的 AsrProvider(fireredasr / openai-compatible)—
            # 與索引路徑同一實作;fireredasr 內部自帶推論鎖(FIRERED_INFER_LOCK)
            def _run_cfg_provider():
                t_compute = time.time()
                r = cfg_provider.transcribe(
                    audio_path=effective_path, file_name=file_name)
                return r.text, time.time() - t_compute

            text, compute_seconds = await run_in_threadpool(_run_cfg_provider)
            text = text.strip()
            detected_lang = None
        elif whisper_model is not None:
            # 直接呼叫底層 whisper.Whisper.transcribe → 完整 language + initial_prompt 控制
            # 用 lock serialize 避免 KV-cache race(PyTorch transformer 不是 thread-safe)。
            # 內部分別計時 lock-wait 跟真推論,讓 metric 區分 queue / compute 兩種延遲。
            def _run_whisper():
                with _WHISPER_INFER_LOCK:
                    t_compute = time.time()
                    result = whisper_model.transcribe(
                        effective_path,
                        language=language,
                        initial_prompt=prompt,
                        verbose=False,
                        word_timestamps=False,
                    )
                    return result, time.time() - t_compute

            result, compute_seconds = await run_in_threadpool(_run_whisper)
            text = result.get("text", "").strip()
            detected_lang = result.get("language")
        else:
            # AsrPipeline 還沒 warm → fallback docling.convert(失去 language/prompt)
            def _run_docling_asr():
                with _DOCLING_INFER_LOCK:
                    t_compute = time.time()
                    return get_converter().convert(effective_path), time.time() - t_compute

            doc_result, compute_seconds = await run_in_threadpool(_run_docling_asr)
            text = doc_result.document.export_to_markdown()
            detected_lang = None

        total_lock_phase = time.time() - t_lock_request
        wait_seconds = max(0.0, total_lock_phase - compute_seconds)
        logger.info(
            f"[transcribe] · inference done | backend={backend} "
            f"raw_chars={len(text)} detected_lang={detected_lang or '?'} "
            f"compute={compute_seconds:.2f}s wait_for_lock={wait_seconds:.2f}s"
        )

        n_stripped = 0
        if strip_hallucinations:
            t_filter = time.time()
            text, n_stripped = _filter_whisper_hallucinations(text)
            filter_elapsed = time.time() - t_filter
            if n_stripped > 0:
                logger.info(
                    f"[transcribe] · hallucinations stripped | count={n_stripped} "
                    f"final_chars={len(text)} elapsed={filter_elapsed:.3f}s"
                )

        total_elapsed = time.time() - t_start
        # Preview head + tail of transcript so operators can verify content without
        # opening a separate log search. Truncate aggressively (60 + 60 chars) — full
        # transcript is in the response body; this is for quick sanity check.
        def _preview(s: str, n: int = 60) -> str:
            s = " ".join(s.split())  # collapse whitespace for log readability
            if len(s) <= n * 2 + 5:
                return s
            return f"{s[:n]} … {s[-n:]}"

        logger.info(
            f"[transcribe] ⮕ ✓ done | file={file_name} "
            f"size={_fmt_size(bytes_written)} chars={len(text)} "
            f"lang={language or detected_lang or 'auto'} "
            f"trimmed={trimmed_path is not None} "
            f"hallucinations_stripped={n_stripped} "
            f"backend={backend} total_elapsed={total_elapsed:.2f}s"
        )
        logger.info(f"[transcribe] · preview: {_preview(text)!r}")

        if response_format == "text":
            # PlainTextResponse 才會正確設 Content-Type: text/plain
            # 否則 FastAPI 預設 JSON 序列化會把 str 包成 "..."(整段引號 + escape)
            return PlainTextResponse(content=text, media_type="text/plain; charset=utf-8")

        return {
            "text": text,
            "metadata": {
                "model": "whisper-turbo",
                "backend": backend,
                "filename": file_name,
                "file_size_bytes": bytes_written,
                "language": language or detected_lang,
                "prompt_used": bool(prompt),
                "trimmed_leading_silence": trimmed_path is not None,
                "hallucinations_stripped": n_stripped,
                "elapsed_seconds": round(total_elapsed, 2),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"[transcribe] ✗ failed | file={file_name} "
            f"size={_fmt_size(bytes_written)} error={e}"
        )
        raise HTTPException(500, f"Transcription failed: {e}") from e
    finally:
        _unlink_safe(trimmed_path)
        _unlink_safe(transcoded_path)
        _unlink_safe(src_path)


# Response = json {text, pages, mime_type} 或 plain text (response_format=text)
@router.post(
    "/ocr/general",
    summary="Image / PDF → text via Docling OCR",
    description="共用 Docling 已 load 的 OCR pipeline(RapidOCR torch backend)。",
    responses={
        200: {
            "description": "json: {text, pages, mime_type} / text: plain extracted text",
            "content": {
                "application/json": {"example": {"text": "...", "pages": 3, "mime_type": "application/pdf"}},
                "text/plain": {"example": "..."},
            },
        },
        415: {"model": ErrorDetailResponse, "description": "不支援的圖檔 / PDF 格式"},
        500: {"model": ErrorDetailResponse, "description": "OCR 推論失敗"},
    },
)
async def ocr(
    file: UploadFile = File(...),
    response_format: str = Form("json"),
):
    """Args:
        file:             圖片或 PDF(png / jpg / bmp / tiff / webp / pdf …)
        response_format:  json | text(預設 json)
    """
    t_start = time.time()
    file_name = file.filename or "image"
    ext = Path(file_name).suffix.lower()
    logger.info(
        f"[ocr] ⮕ request received | file={file_name} ext={ext} "
        f"content_type={file.content_type} response_format={response_format}"
    )
    if ext not in _IMAGE_EXTS:
        logger.warning(f"[ocr] ✗ rejected unsupported ext={ext} for {file_name}")
        raise HTTPException(415, f"Unsupported format: {ext}. Allowed: {sorted(_IMAGE_EXTS)}")

    t_save = time.time()
    src_path, bytes_written = await _save_upload_to_temp(file)
    save_elapsed = time.time() - t_save
    logger.info(
        f"[ocr] · upload saved | size={_fmt_size(bytes_written)} "
        f"tmp={src_path} save_elapsed={save_elapsed:.2f}s"
    )

    try:
        queued = _DOCLING_INFER_LOCK.locked()
        if queued:
            logger.info("[ocr] · docling pipeline queued (another request holds docling lock)")
        else:
            logger.info("[ocr] · docling pipeline start")
        t_lock_request = time.time()

        # docling 的 PdfPipeline 內有 TableFormer transformer + RapidOCR session,
        # 同樣 thread-safety 顧慮,serialize。同步分計 lock-wait / compute。
        def _run_docling_ocr():
            with _DOCLING_INFER_LOCK:
                t_compute = time.time()
                return get_converter().convert(src_path), time.time() - t_compute

        result, compute_seconds = await run_in_threadpool(_run_docling_ocr)
        text = result.document.export_to_markdown()
        total_lock_phase = time.time() - t_lock_request
        wait_seconds = max(0.0, total_lock_phase - compute_seconds)
        logger.info(
            f"[ocr] · docling pipeline done | chars={len(text)} "
            f"compute={compute_seconds:.2f}s wait_for_lock={wait_seconds:.2f}s"
        )

        total_elapsed = time.time() - t_start
        logger.info(
            f"[ocr] ⮕ ✓ done | file={file_name} size={_fmt_size(bytes_written)} "
            f"chars={len(text)} total_elapsed={total_elapsed:.2f}s"
        )

        if response_format == "text":
            # Match STT endpoint: text/plain instead of JSON-encoded string
            return PlainTextResponse(content=text, media_type="text/plain; charset=utf-8")

        return {
            "text": text,
            "metadata": {
                "model": "docling-ocr",
                "filename": file_name,
                "file_size_bytes": bytes_written,
                "elapsed_seconds": round(total_elapsed, 2),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"[ocr] ✗ failed | file={file_name} "
            f"size={_fmt_size(bytes_written)} error={e}"
        )
        raise HTTPException(500, f"OCR failed: {e}") from e
    finally:
        _unlink_safe(src_path)


# Response = {object: "list", data: [{id, object, type, owned_by, backend, warmed}, ...]}
# 對齊 OpenAI /v1/models 風格;type ∈ "transcription" / "ocr"
@router.get(
    "/models",
    summary="List loaded media models",
    description="回報 Docling 已 load 的 STT / OCR pipeline 狀態。",
    responses={500: {"model": ErrorDetailResponse}},
)
async def list_models():
    """OpenAI `/v1/models` 風格的回應。"""
    try:
        from docling.datamodel.base_models import InputFormat
        converter = get_converter()
        fmt_opts = getattr(converter, "format_to_options", {}) or {}
        # initialized_pipelines is a dict keyed by (PipelineClass, hash); check class names
        pipeline_classes = {
            getattr(key[0], "__name__", "") for key in
            getattr(converter, "initialized_pipelines", {}).keys()
        }

        data = []
        if InputFormat.AUDIO in fmt_opts:
            data.append({
                "id": "whisper-turbo",
                "object": "model",
                "type": "transcription",
                "owned_by": "openai",
                "backend": "docling+whisper",
                "warmed": "AsrPipeline" in pipeline_classes,
            })
        if InputFormat.PDF in fmt_opts or InputFormat.IMAGE in fmt_opts:
            data.append({
                "id": "docling-ocr",
                "object": "model",
                "type": "ocr",
                "owned_by": "ibm-docling",
                "backend": "rapidocr-torch",
                "warmed": "StandardPdfPipeline" in pipeline_classes,
            })
        return {"object": "list", "data": data}
    except Exception as e:
        logger.error(f"[list_models] failed: {e}")
        raise HTTPException(500, f"Failed to query models: {e}") from e
