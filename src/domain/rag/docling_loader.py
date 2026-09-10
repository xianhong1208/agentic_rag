
"""Docling-based document loader with structure-aware chunking

Uses IBM's Docling to parse PDF/DOCX/PPTX with full structure preservation:
- Tables are kept as complete Markdown chunks (never split)
- Document hierarchy (headings, sections) is respected
- HybridChunker ensures chunks fit within embedding model token limits

Replaces: SimpleDirectoryReader + SentenceSplitter for structured documents.

Device 設定來自 config.yaml：
    rag:
      docling:
        device: "cuda:4"    # "cpu", "cuda", "cuda:0", "cuda:4"
        ocr_enabled: true
        hf_offline: true     # 打包環境建議開啟
"""

from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Any, List, Optional

from src.log import get_api_logger
from src.utils.runtime_paths import resolve_external_dir

logger = get_api_logger()

# Supported file types for Docling processing
# 文件類：PDF / Office / 標記語言（一律走 Docling 結構感知 pipeline）
# 圖片類：交給 Docling ImageFormatOption（OCR via RapidOcr in assets/docling_models/RapidOcr）
# 音訊類：交給 Docling AudioFormatOption（ASR via Whisper turbo in assets/whisper_models/turbo.pt）
#         音訊路徑只在 whisper 模型存在時實際啟用，否則 fallback 到 SimpleDirectoryReader
# 格式 v3(docling 2.124 官網全格式對標;每個 InputFormat 的**全部**官方副檔名。
# 對標由 tests/test_upload_formats.py 的程式化不變式把關 — 直接讀 docling 的
# FormatToExtensions 斷言,docling 未來加格式時測試自動紅,對標永不過期。
# 刻意排除的格式與理由見該測試的 _EXCLUDED_FORMATS)
DOCLING_EXTENSIONS = {
    # PDF / Office Open XML(含範本/巨集變體)
    ".pdf",
    ".docx", ".dotx", ".docm", ".dotm",
    ".pptx", ".ppsx", ".pptm", ".potm", ".ppsm",  # potx 實測 docling 打不開
    ".xlsx", ".xlsm",
    # Legacy Office(docling 2.119+;內部經 LibreOffice `soffice` 轉現代格式
    # 再解析 — ⚠️ 部署映像/機器必須裝 libreoffice-writer,缺了會在索引時
    # 明確報錯。品質已實測:.doc 與 .docx 同內容 51 chunks 一致、行重合 96%)
    ".doc", ".dot", ".xls", ".xlt", ".ppt", ".pot", ".pps",
    # OpenDocument(含範本變體)
    ".odt", ".ods", ".odp",  # 範本變體 ott/ots/otp 實測 docling odfdo backend 打不開
    # 標記 / 科學文件
    ".html", ".htm", ".xhtml", ".md", ".qmd", ".rmd",
    ".adoc", ".asciidoc", ".asc", ".tex", ".latex",
    # 郵件(.msg = python-oxmsg 純 Python;.eml = MIME)/ 電子書 / 字幕
    ".msg", ".eml", ".epub", ".vtt",
    # 圖片
    ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp",
    # 音訊(docling 官方 audio 6 種;轉錄走 AsrProvider)
    ".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac",
}

# 延遲初始化旗標（確保只套用一次）
_docling_env_applied = False

# Singleton DocumentConverter（啟動時預載，避免每次重建模型）
_converter = None
# 建構鎖:get_converter 被 asyncio.to_thread / run_in_threadpool 從多個
# OS thread 呼叫;warmup 失敗時首波並發請求會同時建 DocumentConverter
# (數秒的 GPU 模型載入 ×N → VRAM 浪費/OOM)。推論鎖在 media.py,這裡管建構。
_converter_lock = threading.Lock()
# H2: 推論鎖(與上面的「建構鎖」_converter_lock 不同用途)。converter 是
# process-wide singleton,索引路徑(asyncio.to_thread)與 media 的 /v1/ocr、
# /v1/transcriptions 共用同一顆。TableFormer / RapidOCR / Whisper 同一 model
# instance 並發 forward 會 KV-cache race → tensor reshape 錯、CUDA illegal
# memory、OOM。所有 converter.convert() 都必須在這把鎖內序列化。
# ⚠️ media.py 也 import 這同一把(見其檔頭),不要各開各的。
DOCLING_INFER_LOCK = threading.Lock()

# HuggingFace tokenizer 快取（依本地路徑為 key），避免重複載入
_tokenizer_cache: dict[str, Any] = {}

# ---------------------------------------------------------------------------
# 頁級解析進度(OCR 進度條)
# docling 沒有 progress callback,但 PaginatedPipeline._apply_on_pages 逐頁
# yield — 用 generator 包裝觀察,每完成一頁回報 ("loading", done, total)。
# thread-local:convert 在單一 worker thread 內同步執行,不同檔案互不干擾;
# media.py 的 OCR 路徑不設定 → 零行為變化。
# ---------------------------------------------------------------------------
import threading as _threading

_page_progress_tls = _threading.local()
_page_patch_installed = False


class _PageNotifyList(list):
    """append 時回報頁級進度的 list — 換進 ProcessingResult.pages/failed_pages。

    ⚠️ 前提:docling 2.119 threaded 管線的「收集迴圈」(proc.pages.append)
    跑在呼叫 convert 的同一條 thread(worker stages 只寫 queue),所以這裡
    讀 ctx 不需要跨執行緒同步 — 這個前提若在未來版本破掉,症狀是進度
    歸零(ctx 是 TLS,worker thread 讀不到),不會錯亂或崩潰。
    """

    def __init__(self, ctx: dict):
        super().__init__()
        self._ctx = ctx

    def append(self, item):
        super().append(item)
        ctx = self._ctx
        ctx["done"] += 1
        cb = ctx.get("cb")
        if cb is not None:
            try:
                cb("loading", ctx["done"], ctx.get("total"))
            except Exception:  # 進度回報絕不能弄死解析
                pass


def _install_page_progress_patch() -> None:
    """安裝頁級進度觀察者(冪等)。純觀察:TLS 未設定時零行為變化。

    兩代 docling 的掛點不同,都裝、各自防禦:
    - 2.118+:StandardPdfPipeline 是 threaded staged 管線,收集迴圈在呼叫端
      thread 逐頁 append 進 ProcessingResult → 換成 _PageNotifyList
    - ≤2.111:StandardPdfPipeline 繼承 PaginatedPipeline,逐頁流過
      _apply_on_pages generator → 包一層計數
    """
    global _page_patch_installed
    if _page_patch_installed:
        return
    _page_patch_installed = True

    # --- 掛點 1:2.118+ threaded 管線 ---
    try:
        from docling.pipeline.standard_pdf_pipeline import ProcessingResult

        _orig_init = ProcessingResult.__init__

        def _init_with_progress(self, *args, **kwargs):
            _orig_init(self, *args, **kwargs)
            ctx = getattr(_page_progress_tls, "ctx", None)
            if ctx is not None:
                # dataclass 純屬性替換;success_count/failure_count 走 len(),
                # list 子類完全相容
                self.pages = _PageNotifyList(ctx)
                self.failed_pages = _PageNotifyList(ctx)

        ProcessingResult.__init__ = _init_with_progress
        logger.info("[DOCLING] page-progress observer installed (ProcessingResult)")
    except ImportError:
        pass

    # --- 掛點 2:≤2.111 分頁管線 ---
    try:
        from docling.pipeline.base_pipeline import PaginatedPipeline

        _orig_apply = PaginatedPipeline._apply_on_pages

        def _apply_with_progress(self, conv_res, page_batch):
            ctx = getattr(_page_progress_tls, "ctx", None)
            for page in _orig_apply(self, conv_res, page_batch):
                if ctx is not None:
                    ctx["done"] += 1
                    cb = ctx.get("cb")
                    if cb is not None:
                        try:
                            cb("loading", ctx["done"], ctx.get("total"))
                        except Exception:
                            pass
                yield page

        PaginatedPipeline._apply_on_pages = _apply_with_progress
        logger.info("[DOCLING] page-progress observer installed (PaginatedPipeline)")
    except (ImportError, AttributeError):
        pass


def _pdf_page_count(file_path: str) -> Optional[int]:
    """pymupdf 秒算 PDF 總頁數(進度條分母);非 PDF / 開檔失敗回 None。"""
    try:
        import fitz
        with fitz.open(file_path) as doc:
            return len(doc)
    except Exception:
        return None


def resolve_assets_dir() -> Optional[Path]:
    """解析 assets/ 資源目錄（共用 API，document_indexer.py 也會 import 這個）

    資源目錄放 ML 模型、tokenizer、nltk_data 等「打包時要一起帶走」的檔案。
    真正的查找邏輯在 src.utils.runtime_paths.resolve_external_dir，這裡只是綁定
    `name="assets"` 和 dev_root 的 thin wrapper。

    備註：打包後的 libs/ 會被 .venv site-packages 佔用，所以 ML 資產獨立
    放 assets/，絕對不要再改回 libs/。
    """
    return resolve_external_dir(
        "assets",
        dev_root=Path(__file__).resolve().parents[3],
    )


def _resolve_artifacts_path() -> Optional[Path]:
    """解析 Docling ML 模型目錄：assets/docling_models

    由 `docling-tools models download -o assets/docling_models` 產出。找不到回 None。
    """
    assets = resolve_assets_dir()
    if assets:
        p = assets / "docling_models"
        if p.is_dir():
            return p
    return None


def _resolve_whisper_path() -> Optional[Path]:
    """解析 Whisper ASR 模型目錄：assets/whisper_models

    `whisper.load_model('turbo', download_root=...)` 會把權重存成 `large-v3-turbo.pt`
    （OpenAI 內部把 alias 'turbo' 映射成正式檔名）。我們不綁死檔名，只要目錄裡
    至少存在一個 .pt 檔就視為「whisper 已備妥」。

    auto-discover 設計：找不到目錄或無 .pt 檔 → 回 None → audio pipeline 不會被裝上去
    → 上傳 .wav/.mp3 自然走 SimpleDirectoryReader fallback（無聲失敗，符合最小驚喜原則）。
    """
    assets = resolve_assets_dir()
    if not assets:
        return None
    p = assets / "whisper_models"
    if p.is_dir() and any(p.glob("*.pt")):
        return p
    return None


def asr_wants_local_whisper() -> bool:
    """config `rag.asr` 是否要求本地 docling-whisper。

    掛載(get_converter)與 warmup(warmup_docling)必須用**同一個**條件 —
    兩者曾各自判斷(warmup 只看權重檔在不在),provider 切 fireredasr 且機器
    殘留 whisper .pt 時,warmup 會去 init 一條沒 artifacts_path 的 docling
    預設 audio pipeline → 觸發執行期下載 → 離線/攔截環境炸 SSL。
    config 缺省(None)維持舊 auto-discover 語義(要)。
    """
    try:
        from src.config.config_manager import Config as _Cfg
        _asr_cfg = getattr(getattr(_Cfg.get_config_model(), "rag", None), "asr", None)
        if _asr_cfg is not None:
            return bool(_asr_cfg.enabled and _asr_cfg.provider == "docling-whisper")
    except Exception:
        pass  # config 讀不到 → 維持舊行為
    return True


def _resolve_tokenizer_path(embedding_model_name: Optional[str]) -> Optional[Path]:
    """解析 HybridChunker 用的本地 HF tokenizer 路徑(支援 fallback)。

    路徑:`assets/hf_tokenizers/<mangled>`(BAAI/bge-m3 → BAAI--bge-m3)。
    chunker tokenizer 只負責「算 token 數決定切點」,跟 embedding model 不必一致,
    所以精確匹配失敗時 fallback 到任一已存在的 tokenizer。

    Args:
        embedding_model_name: 想對齊的 model 名(e.g. `BAAI/bge-m3`)。

    Returns:
        絕對路徑字串;完全找不到時 raise。
    """
    assets = resolve_assets_dir()
    if not assets:
        return None
    tokenizers_dir = assets / "hf_tokenizers"
    if not tokenizers_dir.is_dir():
        return None

    if embedding_model_name:
        mangled = embedding_model_name.replace("/", "--")
        exact = tokenizers_dir / mangled
        if exact.is_dir():
            return exact

    fallback = next(
        (p for p in sorted(tokenizers_dir.iterdir()) if p.is_dir()),
        None,
    )
    if fallback:
        logger.info(
            f"[DOCLING] No exact tokenizer match for '{embedding_model_name}'; "
            f"falling back to local tokenizer '{fallback.name}' for chunk token counting"
        )
    return fallback


def _load_local_tokenizer(path: Path):
    """從本地目錄載入 AutoTokenizer 並快取。"""
    key = str(path)
    if key not in _tokenizer_cache:
        from transformers import AutoTokenizer
        logger.info(f"[DOCLING] Loading local tokenizer from {path}")
        _tokenizer_cache[key] = AutoTokenizer.from_pretrained(str(path))
    return _tokenizer_cache[key]


def get_hf_tokenizer(tokenizer_name: Optional[str]):
    """解析並載入 HF tokenizer(本地 assets 優先,offline 時缺檔大聲失敗)。

    docling 路徑與 fallback(非 docling 檔型)切分共用同一顆 tokenizer,
    保證兩條路徑的 token budget 用同一把尺(bge-m3)量。

    Args:
        tokenizer_name: HF 模型名(如 "BAAI/bge-m3");None 時走線上 fallback。

    Returns:
        AutoTokenizer instance(本地載入會經 _load_local_tokenizer 快取)。

    Raises:
        RuntimeError: HF_HUB_OFFLINE=1 且 assets/hf_tokenizers 找不到對應目錄。
    """
    local_tok_path = _resolve_tokenizer_path(tokenizer_name)
    if local_tok_path:
        return _load_local_tokenizer(local_tok_path)
    offline = os.environ.get("HF_HUB_OFFLINE") == "1"
    if offline:
        mangled = (tokenizer_name or "").replace("/", "--")
        raise RuntimeError(
            f"[DOCLING] hf_offline=true but no local tokenizer found for "
            f"'{tokenizer_name}'. Expected at assets/hf_tokenizers/{mangled}"
        )
    # Legacy fallback — first use will hit HF Hub。 Acceptable since
    # production sets HF_HUB_OFFLINE=1 + local tokenizer assets。
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained(tokenizer_name)


def _apply_docling_env():
    """從 config 讀取 Docling 設定並套用到環境變數

    延遲到第一次使用 Docling 時才執行，此時 Config 已經載入。
    只執行一次，透過 _docling_env_applied 旗標控制。

    注意:device 設定不再透過 DOCLING_DEVICE env var(Docling 不讀這個)。
    實際 GPU 啟用點在 `_get_accelerator_options()` 透過 AcceleratorOptions
    傳入 PdfPipelineOptions / AsrPipelineOptions。
    """
    global _docling_env_applied
    if _docling_env_applied:
        return
    _docling_env_applied = True

    try:
        from src.config.config_manager import Config
        config = Config.get_config_model()

        if config and config.rag:
            docling_config = getattr(config.rag, 'docling', None)

            if docling_config:
                device = docling_config.device or "cpu"
                # 保留 DOCLING_DEVICE env var(向後相容,給 debug 看用)。
                # 真正生效的入口是 _get_accelerator_options()。
                os.environ["DOCLING_DEVICE"] = device
                logger.info(f"[DOCLING_INIT] device={device} (resolves to AcceleratorOptions)")

                # docling 2.119 起 AcceleratorOptions 支援 "cuda:N"(見
                # _get_accelerator_options),cuda:N 會真的釘到第 N 張卡。
                # ⚠️ 若同時設了 CUDA_VISIBLE_DEVICES,N 是「重映射後」的序號 —
                # 兩個一起用容易誤指(例:CUDA_VISIBLE_DEVICES=4 + device=cuda:4
                # → 找不到第 5 張可見卡而炸)。共用卡場景二擇一:
                #   (a) device=cuda:4 + 不設 CUDA_VISIBLE_DEVICES(推薦,直觀)
                #   (b) CUDA_VISIBLE_DEVICES=4 + device=cuda:0(隔離更徹底)
                if device.startswith("cuda:") and os.environ.get("CUDA_VISIBLE_DEVICES"):
                    logger.warning(
                        f"[DOCLING_INIT] device='{device}' 與 "
                        f"CUDA_VISIBLE_DEVICES={os.environ['CUDA_VISIBLE_DEVICES']} "
                        f"同時設定:cuda:N 的 N 是重映射後序號,請確認指到對的卡"
                    )

                # HuggingFace 離線模式
                if docling_config.hf_offline:
                    os.environ["HF_HUB_OFFLINE"] = "1"
                    logger.info("[DOCLING_INIT] HuggingFace offline mode enabled")

                # torch.compile 開關（關閉可加速啟動 ~120s，但推理略慢）
                if not docling_config.compile_models:
                    os.environ["DOCLING_INFERENCE"] = '{"compile_torch_models": false}'
                    logger.info("[DOCLING_INIT] torch.compile disabled (faster startup)")

                # OCR 開關
                if not docling_config.ocr_enabled:
                    os.environ["DOCLING_OCR_ENABLED"] = "false"
                    logger.info("[DOCLING_INIT] OCR disabled")

                return

    except Exception as e:
        logger.warning(f"[DOCLING_INIT] Failed to read config, using defaults: {e}")

    # Fallback
    if "DOCLING_DEVICE" not in os.environ:
        os.environ["DOCLING_DEVICE"] = "cpu"
        logger.info("[DOCLING_INIT] device=cpu (default)")


def _get_rapidocr_options(artifacts_path, accelerator_options=None):
    """依 config.rag.docling.ocr_model_scale 組 RapidOcrOptions(PP-OCRv6, torch backend)。

    OCR 推論引擎統一走 rapidocr 的 torch backend,不再用 onnxruntime:
    - 跟 docling 其他模型(layout/表格)共用同一份 torch — CUDA / ROCm 都
      直接吃到 GPU(ROCm 的 torch 偽裝成 cuda device,不需分流)
    - pyproject 從此不必依 GPU 種類維護 onnxruntime 變體(gpu/rocm/cpu)
    - docling 2.111 對 torch backend 的 EngineConfig.torch.use_cuda 是接好的
      (斷線 bug 只在 onnxruntime engine),舊的 GPU key 修補一併退役

    模型:PP-OCRv6 det/rec 官方 torch 權重(RapidAI 轉檔,精度同 onnx 版;
    tiny/small/medium 三個 scale 都有)+ PP-OCRv4 v2.0 cls(torch 目前唯一
    的 cls 權重;cls 只判斷文字行 0/180 方向,版本差異無感)。
    torch 權重不內嵌字典,rec 必須帶 rec_keys_path(tiny 用專屬字典)。

    Args:
        artifacts_path: assets/docling_models 路徑(Path)。
        accelerator_options: docling AcceleratorOptions。GPU 開關不在這裡處理 —
            docling 的 RapidOcrModel 會自己從 accelerator device 算
            EngineConfig.torch.use_cuda / device_id;僅留作 log。

    Returns:
        RapidOcrOptions(backend="torch" + 明確模型路徑)。
    """
    scale = "small"
    try:
        from src.config.config_manager import Config
        config = Config.get_config_model()
        if config and config.rag and config.rag.docling:
            scale = (config.rag.docling.ocr_model_scale or "small").lower()
    except Exception:
        pass

    if scale not in ("tiny", "small", "medium"):
        logger.warning(f"[DOCLING] unknown ocr_model_scale='{scale}', fallback to small")
        scale = "small"

    rapid_root = Path(artifacts_path) / "RapidOcr"
    det = rapid_root / "torch" / "PP-OCRv6" / "det" / f"PP-OCRv6_det_{scale}.pth"
    rec = rapid_root / "torch" / "PP-OCRv6" / "rec" / f"PP-OCRv6_rec_{scale}.pth"
    cls = rapid_root / "torch" / "PP-OCRv4" / "cls" / "ch_ptocr_mobile_v2.0_cls_mobile.pth"
    # tiny 的 rec 字典跟 small/medium 不同(字符集較小),不能混用
    dict_name = "ppocrv6_tiny_dict.txt" if scale == "tiny" else "ppocrv6_dict.txt"
    rec_keys = rapid_root / "paddle" / "PP-OCRv6" / "rec" / dict_name

    missing = [str(p) for p in (det, rec, cls, rec_keys) if not p.exists()]
    if missing:
        # 不做 fallback:docling 的 torch 預設是 PP-OCRv4 且檔案同樣不在 assets,
        # 靜默降級只會把錯誤往後推。讓 rapidocr 在模型載入時大聲失敗,
        # 部署端才知道 assets 沒帶齊。
        logger.error(
            f"[DOCLING] OCR torch 模型檔缺失(scale={scale}):{missing} — "
            f"請確認打包時 assets/docling_models/RapidOcr/torch/ 有帶出"
        )

    device_str = str(getattr(accelerator_options, "device", "") or "").lower()
    from docling.datamodel.pipeline_options import RapidOcrOptions
    logger.info(
        f"[DOCLING] OCR = PP-OCRv6 {scale} det/rec + cls v2.0 mobile "
        f"(torch backend, device={device_str or 'auto'})"
    )
    return RapidOcrOptions(
        backend="torch",
        det_model_path=str(det),
        rec_model_path=str(rec),
        cls_model_path=str(cls),
        rec_keys_path=str(rec_keys),
    )


def _get_accelerator_options():
    """從 config 算出 Docling AcceleratorOptions。

    Returns:
        AcceleratorOptions instance with device 對應 config.rag.docling.device。
        如果 config 設 cuda* 但 PyTorch 看不到 GPU,自動降級 CPU 並 warn。
    """
    from docling.datamodel.pipeline_options import AcceleratorOptions, AcceleratorDevice

    device_str = os.environ.get("DOCLING_DEVICE", "cpu").lower()

    if device_str.startswith("cuda"):
        # Cross-check GPU 真的可用,避免 silent fallback
        try:
            import torch
            if not torch.cuda.is_available():
                logger.warning(
                    f"[DOCLING_INIT] config device='{device_str}' but "
                    f"torch.cuda.is_available()=False — fallback CPU"
                )
                return AcceleratorOptions(device=AcceleratorDevice.CPU, num_threads=4)
        except ImportError:
            logger.warning("[DOCLING_INIT] torch not importable, fallback CPU")
            return AcceleratorOptions(device=AcceleratorDevice.CPU, num_threads=4)

        # docling 2.119 的 AcceleratorOptions.device 直接吃 "cuda:N" 字串
        # (validator 收 ^cuda(:\d+)?$)。原樣傳入 → 真的釘到指定卡,不再
        # 被砍成裸 CUDA(GPU 0)。共用卡場景靠這個把 docling 跟 vLLM 分開,
        # 避開 GPU 0 上 gpt-oss 佔滿導致的 CUBLAS_ALLOC_FAILED。
        # ⚠️ 索引語意:docling 用的是「PyTorch 可見的第 N 張卡」。若同時設了
        # CUDA_VISIBLE_DEVICES,N 是重映射後的序號(見 _apply_docling_env 警告)。
        logger.info(
            f"[DOCLING_INIT] Using device='{device_str}' "
            f"(CUDA_VISIBLE_DEVICES={os.environ.get('CUDA_VISIBLE_DEVICES', 'all')})"
        )
        return AcceleratorOptions(device=device_str, num_threads=4)

    if device_str == "mps":
        return AcceleratorOptions(device=AcceleratorDevice.MPS, num_threads=4)

    return AcceleratorOptions(device=AcceleratorDevice.CPU, num_threads=4)


# 音訊副檔名單獨列出 — 需要 Whisper 模型才實際支援
_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac"}  # docling 官方 6 種


def is_docling_supported(file_name: str) -> bool:
    """判斷檔案是否能用 Docling 處理。

    音訊檔 (.wav / .mp3) 需 assets/whisper_models/turbo.pt 存在;否則視為不支援,
    讓 caller fallback 去 SimpleDirectoryReader。

    Args:
        file_name: 含副檔名的檔名。

    Returns:
        True = Docling 可處理;False = 走 fallback。
    """
    ext = Path(file_name).suffix.lower()
    if ext not in DOCLING_EXTENSIONS:
        return False
    if ext in _AUDIO_EXTENSIONS and _resolve_whisper_path() is None:
        return False
    return True


def get_converter():
    """取得 singleton DocumentConverter（thread-safe），若尚未初始化則建立

    首次呼叫會載入所有 ML 模型（layout, table structure, OCR），
    後續呼叫直接回傳已建立的實例。

    double-checked locking:已建好走 fast path 免鎖;未建好搶鎖後由
    _build_converter 的 None 檢查做第二次確認 — 併發首觸只會建一次。
    """
    global _converter
    if _converter is not None:
        return _converter
    with _converter_lock:
        return _build_converter()


def _build_converter():
    """實際建構 singleton(呼叫方必須持有 _converter_lock)。

    離線部署（hf_offline=true）：強制使用 assets/docling_models 的本地模型，
    找不到就直接 raise，避免後續上傳檔案才爆。
    """
    global _converter
    if _converter is None:
        _apply_docling_env()  # 必須先跑：hf_offline=true 會設 HF_HUB_OFFLINE=1

        artifacts_path = _resolve_artifacts_path()
        offline = os.environ.get("HF_HUB_OFFLINE") == "1"

        if not artifacts_path and offline:
            raise RuntimeError(
                "[DOCLING] hf_offline=true but assets/docling_models not found. "
                "Prepare via: `uv run docling-tools models download -o assets/docling_models`"
            )

        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions, AsrPipelineOptions
        from docling.datamodel.asr_model_specs import WHISPER_TURBO_NATIVE
        from docling.document_converter import (
            DocumentConverter,
            PdfFormatOption,
            ImageFormatOption,
            AudioFormatOption,
        )

        format_options: dict = {}

        # 從 config 算出 GPU/CPU 選擇 — 傳給所有 pipeline option,讓 Docling
        # Layout / TableFormer / OCR / Whisper 都跑在配置的 device 上
        accelerator_options = _get_accelerator_options()

        if artifacts_path:
            logger.info(f"[DOCLING] Using local artifacts_path: {artifacts_path}")
            pdf_kwargs = {
                "artifacts_path": str(artifacts_path),
                "accelerator_options": accelerator_options,
            }
            # OCR 走 rapidocr torch backend(PP-OCRv6,依 ocr_model_scale 選檔)
            ocr_options = _get_rapidocr_options(artifacts_path, accelerator_options)
            if ocr_options is not None:
                pdf_kwargs["ocr_options"] = ocr_options
            pdf_pipeline_options = PdfPipelineOptions(**pdf_kwargs)
            # PDF 與 Image 共用同一份 pipeline_options（IMAGE 內部就是走 StandardPdfPipeline）
            format_options[InputFormat.PDF] = PdfFormatOption(pipeline_options=pdf_pipeline_options)
            format_options[InputFormat.IMAGE] = ImageFormatOption(pipeline_options=pdf_pipeline_options)
        else:
            logger.warning(
                "[DOCLING] No local artifacts_path; models will be fetched from HuggingFace Hub "
                "on first use (online machines only)"
            )

        # Audio pipeline:Whisper 模型存在 + config 允許才掛(BL-06)。
        # rag.asr.enabled=false 或 provider 非 docling-whisper(如雲端)時不掛,
        # 省下本地 whisper 的顯存/warmup;config 缺省維持舊 auto-discover 語義。
        whisper_path = _resolve_whisper_path() if asr_wants_local_whisper() else None
        if whisper_path is None and not asr_wants_local_whisper():
            logger.info("[DOCLING] Audio pipeline skipped by rag.asr config (disabled or non-local provider)")
        if whisper_path:
            logger.info(f"[DOCLING] Audio pipeline enabled, whisper_models at: {whisper_path}")
            # word_timestamps=False:避開 whisper/timing.py 對 Triton
            # (`triton_ops.dtw_kernel` / `median_filter_cuda`)的硬依賴 —
            # 該 API 在不同 Triton/ROCm 版本間不穩定,而我們不需要 word-level
            # timestamps。docling 2.111 起這是正式選項(舊版寫死 True,得用
            # PatchedAsrPipeline 整類覆寫;該檔已隨 2.119 升級移除)。
            asr_pipeline_options = AsrPipelineOptions(
                artifacts_path=str(whisper_path),
                asr_options=WHISPER_TURBO_NATIVE.model_copy(
                    update={"word_timestamps": False}
                ),
                accelerator_options=accelerator_options,
            )
            format_options[InputFormat.AUDIO] = AudioFormatOption(
                pipeline_options=asr_pipeline_options,
            )
        else:
            logger.info("[DOCLING] assets/whisper_models/turbo.pt not found — audio uploads will fallback to SimpleDirectoryReader")

        converter_kwargs = {"format_options": format_options} if format_options else {}

        logger.info("[DOCLING] Creating DocumentConverter (loading ML models)...")
        t0 = time.time()
        _converter = DocumentConverter(**converter_kwargs)
        elapsed = time.time() - t0
        logger.info(f"[DOCLING] DocumentConverter ready ({elapsed:.1f}s)")
    return _converter


def warmup_docling():
    """啟動時預載 Docling 模型

    在 app startup 呼叫，讓 ML 模型提前載入到 GPU/CPU。
    使用 DocumentConverter.initialize_pipeline() 直接初始化 PDF pipeline，
    強制載入所有 ML 模型（Layout Detection、TableFormer、OCR），不需要 dummy PDF。
    """
    logger.info("[DOCLING_WARMUP] Pre-loading Docling models...")
    t0 = time.time()
    try:
        converter = get_converter()

        # 強制初始化所有要 expose 給 /v1/transcriptions/general、/v1/ocr/general 的 pipeline,
        # 確保啟動完成後第一個 REST 請求不會付 cold-start 模型載入成本。
        from docling.datamodel.base_models import InputFormat
        warmup_formats = [InputFormat.PDF, InputFormat.DOCX, InputFormat.IMAGE]
        # AUDIO warmup 條件必須與 get_converter 的掛載條件一致(config + 權重)—
        # 只看權重檔會在 provider 非 docling-whisper 時暖到 docling 預設
        # audio pipeline(無 artifacts_path → 執行期下載 → 離線環境 SSL 炸)
        _local_whisper = asr_wants_local_whisper() and _resolve_whisper_path() is not None
        if _local_whisper:
            warmup_formats.append(InputFormat.AUDIO)
        for fmt in warmup_formats:
            try:
                logger.info(f"[DOCLING_WARMUP] Initializing pipeline for {fmt.value}...")
                converter.initialize_pipeline(fmt)
            except Exception as e:
                logger.warning(f"[DOCLING_WARMUP] Pipeline init for {fmt.value} failed: {e}")

        # Verify Whisper anti-hallucination monkey-patch actually took effect.
        # 若 Docling 在 hierarchical_indexer 載入前已 import whisper,patch 不到那一份
        # → Layer 1 防線靜默失效。在 audio pipeline warmup 後立刻 assert,失敗時 log error
        # 讓 ops 一眼看到(不 raise — 避免堵住 server 啟動,degraded 仍可用)。
        if _local_whisper:
            try:
                import whisper as _w
                if not getattr(_w.load_model, "_anti_hallucination_wrapped", False):
                    logger.error(
                        "[DOCLING_WARMUP] ❌ Whisper anti-hallucination monkey-patch NOT applied — "
                        "Layer 1 defense disabled. Check import order in hierarchical_indexer.py"
                    )
                else:
                    logger.info(
                        "[DOCLING_WARMUP] ✓ Whisper anti-hallucination monkey-patch verified"
                    )
            except Exception as exc:
                logger.warning(f"[DOCLING_WARMUP] Could not verify whisper monkey-patch: {exc}")

        # GPU 自我診斷:OCR session 的 CUDA provider 初始化失敗會「靜默」退 CPU
        # (ORT 只對 stderr 碎念),這裡把真相印進正式 log,部署時 docker logs
        # 開頭就能看到 OCR/Layout 實際落在哪個裝置(對照 scripts/probe_gpu_pipeline.py)
        try:
            _log_pipeline_devices(converter)
        except Exception as exc:
            logger.warning(f"[DOCLING_WARMUP] GPU self-check skipped: {exc}")

        elapsed = time.time() - t0
        logger.info(f"[DOCLING_WARMUP] All models loaded successfully ({elapsed:.1f}s)")
    except Exception as e:
        logger.warning(f"[DOCLING_WARMUP] Failed to pre-load models: {e}")
        logger.warning("[DOCLING_WARMUP] Models will be loaded on first document processing")


def _log_pipeline_devices(converter) -> None:
    """把 OCR sessions / Layout 模型的實際 device 印進 log(warmup 自我診斷)。"""
    from docling.datamodel.base_models import InputFormat

    pdf_pipeline = converter._get_pipeline(InputFormat.PDF)

    ocr_model = getattr(pdf_pipeline, "ocr_model", None)
    reader = getattr(ocr_model, "reader", None)
    if reader is not None:
        parts = []
        all_gpu = True
        for part_name in ("text_det", "text_cls", "text_rec"):
            part = getattr(reader, part_name, None)
            sess = getattr(getattr(part, "session", None), "session", None) or getattr(part, "session", None)
            dev = None
            if hasattr(sess, "get_providers"):  # onnxruntime engine(舊部署殘留)
                dev = "cuda" if "CUDAExecutionProvider" in sess.get_providers() else "cpu"
            elif getattr(sess, "device", None) is not None:  # torch engine
                dev = str(sess.device)
            if dev is None:
                continue
            on_gpu = "cuda" in dev.lower()
            all_gpu &= on_gpu
            parts.append(f"{part_name}={'GPU' if on_gpu else 'CPU'}")
        if parts:
            line = f"[DOCLING_WARMUP] OCR sessions: {', '.join(parts)}"
            if all_gpu:
                logger.info(f"{line} ✓")
            else:
                logger.warning(
                    f"{line} — ❌ 有 session 落在 CPU!掃描 PDF 會慢很多。"
                    f"torch engine 下代表 accelerator device 判定為 cpu"
                    f"(檢查 config docling.device 與 torch.cuda.is_available)"
                )

    layout = getattr(pdf_pipeline, "layout_model", None)
    if layout is not None:
        dev = getattr(layout, "device", None) or getattr(layout, "_device", None)
        inner = getattr(layout, "layout_predictor", None) or getattr(layout, "model", None)
        if dev is None and inner is not None:
            dev = getattr(inner, "device", None) or getattr(inner, "_device", None)
        if dev is not None:
            msg = f"[DOCLING_WARMUP] Layout model device: {dev}"
            if "cuda" in str(dev).lower():
                logger.info(f"{msg} ✓")
            else:
                logger.warning(f"{msg} — ❌ 落在 CPU")


# ─── Tokenizer-aware chunking helpers ─────────────────────────────────
# We deliberately *do not* use ``HybridChunker``。 The reason is purely
# performance:HybridChunker's slow path on xlsx (a single 5000-row table
# is one giant HierarchicalChunker output)tokenizes the whole text in a
# slide-window fashion,which runs for tens of minutes on large tables。
# The watchdog (10min) and per-file timeout (30min) both fire on these
# documents and the indexing job ends up FAILED even though Whisper /
# embedding could have handled the chunks fine。
#
# Below is HybridChunker's contract re-implemented per-chunk:
#   1. ``HierarchicalChunker`` does the structural pre-split (fast, no
#      tokenizer)。 For PDF / docx that already yields right-sized
#      chunks。 For xlsx 巨表 it yields one big chunk which we then refine。
#   2. For each chunk we ``tokenizer.encode(chunk.text)`` once — bounded
#      by the chunk's own size,not the document's,so the per-call cost
#      stays in the millisecond range even for 5000-row tables。
#   3. Oversized chunks get split by natural boundaries (\n row /
#      paragraph,sentence terminator,then char as last resort);
#      every sub-chunk is tokenizer-verified ≤ max_tokens。
#   4. Short chunks accumulate into a buffer and emit when they cross
#      max_tokens // 2 — mirrors HybridChunker's ``merge_peers=True``。
#   5. When a markdown-table chunk is split,the header row is repeated
#      on continuation chunks — mirrors ``repeat_table_header=True``。
#
# The output chunk shape is text-only (no DocMeta) since the downstream
# consumer at ``HierarchicalIndexer`` only needs text。 If we ever need
# structural metadata back, return DocChunk objects instead of strings。


# Markdown table separator pattern:`| --- | :---: | ... |`。
# Used to detect "this chunk is a markdown table so its first 2 lines
# are the header to repeat on splits"。
_MD_TABLE_SEPARATOR_RE = re.compile(r'^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$')

# Sentence terminators for CJK + ASCII。 Used when a single
# newline-delimited line is itself too big and has no row structure。
_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?。!?])\s+')


def _detect_table_header(lines: List[str]) -> Optional[str]:
    """If ``lines`` is a markdown table, return the header + separator
    block to prepend on continuation chunks。 ``None`` otherwise。"""
    if len(lines) < 2:
        return None
    first = lines[0].strip()
    second = lines[1].strip()
    if "|" in first and _MD_TABLE_SEPARATOR_RE.match(second):
        return f"{lines[0]}\n{lines[1]}"
    return None


def _count_tokens(tokenizer, text: str) -> int:
    """Single-call token count。 ``add_special_tokens=False`` matches the
    HuggingFace BPE-level count;HybridChunker uses the same flag for
    its own ≤ max_tokens checks。"""
    return len(tokenizer.encode(text, add_special_tokens=False))


def _split_by_lines(
    text: str,
    tokenizer,
    max_tokens: int,
    header: Optional[str],
) -> List[str]:
    """Split oversized text by ``\\n`` boundaries (table rows / paragraphs)。

    Each emitted sub-chunk is ≤ max_tokens (verified via tokenizer)。
    When ``header`` is set, continuation sub-chunks get it prepended for
    context (the first sub-chunk already contains it as part of the
    original lines)。 The header's token cost is **reserved upfront for
    every chunk that needs it** so the final assembled chunk stays
    under max_tokens — otherwise the header bytes overflow continuation
    chunks by header_tokens (typically 20-30 tokens for a markdown
    table header), the bug that broke the initial implementation。
    """
    lines = text.split("\n")
    if header is None:
        header = _detect_table_header(lines)

    # Reserve header budget for continuation chunks。 The first chunk
    # already includes the header lines as part of the natural line
    # sequence, so its effective budget is the full max_tokens;
    # continuations get max_tokens - header_tokens to leave room for
    # the prepended header at flush time。
    header_tokens = _count_tokens(tokenizer, header) if header else 0

    out: List[str] = []
    buf: List[str] = []
    buf_tokens = 0

    def _budget() -> int:
        return max_tokens - header_tokens if (header and out) else max_tokens

    def _flush():
        nonlocal buf, buf_tokens
        if not buf:
            return
        body = "\n".join(buf)
        # Continuation chunks (output index > 0) get the header back if
        # the header isn't already the first lines of this buffer。
        if header and out and not body.startswith(header):
            body = f"{header}\n{body}"
        # Tokenizer 可攜性保險:budget 檢查用「各行 token 加總 + 分隔符保留額」,
        # bge-m3 (sentencepiece) 下加總即精確;若未來換成把 \n 算超過 1 token 的
        # tokenizer,這裡做最後一道整塊驗證,超額就 log(不 raise — embedding
        # context 遠大於 max_tokens,超一點不致命,但要看得到)。
        final_tokens = _count_tokens(tokenizer, body)
        if final_tokens > max_tokens:
            logger.warning(
                f"[CHUNK] assembled chunk exceeds budget after join: "
                f"{final_tokens} > {max_tokens} tokens (separator drift); "
                f"check tokenizer newline behaviour"
            )
        out.append(body)
        buf = []
        buf_tokens = 0

    for line in lines:
        if not line.strip():
            continue
        line_tokens = _count_tokens(tokenizer, line)

        # Single line still too big — fall to sentence split。
        # 表格情境下 continuation 也要帶表頭:budget 預留 header,
        # 切完逐塊補 header(修:先前這條路徑的 chunks 會丟失表頭)。
        if line_tokens > _budget():
            _flush()
            sent_budget = max_tokens - header_tokens if header else max_tokens
            for piece in _split_by_sentence(line, tokenizer, sent_budget):
                if header and out and not piece.startswith(header):
                    piece = f"{header}\n{piece}"
                out.append(piece)
            continue

        # Would overflow if we add this line — flush first。
        # `len(buf)` = 加入本行後 join 需要的 \n 分隔符數,對「\n 算 1 token」
        # 的 tokenizer 預留額度(sentencepiece 下略保守,無害)。
        if buf_tokens + line_tokens + len(buf) > _budget():
            _flush()

        buf.append(line)
        buf_tokens += line_tokens

    _flush()
    return out


def _split_by_sentence(text: str, tokenizer, max_tokens: int) -> List[str]:
    """Mid-tier split:break a single line by sentence terminators。

    Reached when a single newline-bounded line is itself > max_tokens —
    typical for long paragraphs without internal structure。
    """
    sentences = _SENTENCE_SPLIT_RE.split(text)
    out: List[str] = []
    buf: List[str] = []
    buf_tokens = 0

    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        sent_tokens = _count_tokens(tokenizer, sent)
        # Single sentence still too big — fall to char-level split
        if sent_tokens > max_tokens:
            if buf:
                out.append(" ".join(buf))
                buf, buf_tokens = [], 0
            out.extend(_split_by_chars(sent, tokenizer, max_tokens))
            continue
        if buf_tokens + sent_tokens > max_tokens:
            out.append(" ".join(buf))
            buf, buf_tokens = [], 0
        buf.append(sent)
        buf_tokens += sent_tokens

    if buf:
        out.append(" ".join(buf))
    return out


def _split_by_chars(text: str, tokenizer, max_tokens: int) -> List[str]:
    """Last-resort character split with tokenizer verification。

    Reached for pathological inputs:single sentences > max_tokens
    (rare in zh / en, common for poorly punctuated dumps or numeric
    sequences)。 We slice by an estimated char-per-token ratio,then
    verify each slice;if the estimate undershot we halve and retry。
    """
    out: List[str] = []
    # Conservative CJK-friendly estimate:1.5 chars per token。 English
    # would be ~3-4, but undershooting just causes one extra verify cycle。
    chars_per_chunk = max(64, int(max_tokens * 1.5))
    i = 0
    while i < len(text):
        piece = text[i:i + chars_per_chunk]
        if _count_tokens(tokenizer, piece) > max_tokens:
            if chars_per_chunk <= 32:
                # 進度保證:已到 32-char 下限仍超 budget(max_tokens 極小 +
                # 高 token 密度字元的病態組合)。硬切送出並前進,
                # 寧可單塊略超也不無限迴圈。
                logger.warning(
                    f"[CHUNK] 32-char piece still exceeds {max_tokens} tokens; "
                    f"emitting oversized piece to guarantee progress"
                )
                out.append(piece)
                i += chars_per_chunk
                continue
            # Estimate too generous — halve and retry without advancing
            chars_per_chunk = max(32, chars_per_chunk // 2)
            continue
        out.append(piece)
        i += chars_per_chunk
    return out


def _chunk_provenance(chunk: Any) -> dict:
    """BL-05: 從 docling chunk 物件抽 headings / page_no(裸字串回空 meta)。

    - headings: HierarchicalChunker 的 meta.headings(章節路徑,list[str])
    - page_no: 第一個 doc_item 的第一個 prov 的 page_no(PDF 有;docx 等通常無)
    抽取全程防禦 — 任何缺欄位都回 None,不影響切分。
    """
    headings = None
    page_no = None
    meta = getattr(chunk, "meta", None)
    if meta is not None:
        h = getattr(meta, "headings", None)
        if h:
            headings = list(h)
        for item in (getattr(meta, "doc_items", None) or []):
            for prov in (getattr(item, "prov", None) or []):
                p = getattr(prov, "page_no", None)
                if p is not None:
                    page_no = int(p)
                    break
            if page_no is not None:
                break
    return {"headings": headings, "page_no": page_no}


def _refine_chunks_for_token_budget(
    raw_chunks: List[Any],
    tokenizer,
    max_tokens: int,
) -> List[dict]:
    """Take HierarchicalChunker output and produce ≤ max_tokens chunk records。

    Implements the same contract HybridChunker enforces (token-bounded,
    merge_peers, repeat_table_header) but with per-chunk tokenize calls
    rather than HybridChunker's whole-document slide-window — which is
    what saves us 30 minutes on xlsx 巨表 cases。

    BL-05: 回傳 chunk 記錄 ``{"text", "headings", "page_no"}``(引用溯源):
    - 過大塊拆分:每段**繼承**源塊的 headings/page_no
    - 小塊合併:取 buffer **首塊**的 meta(合併塊跨 heading 時以起點為準)
    - 裸字串輸入(fallback 切分路徑)meta 為 None
    """
    # merge_peers heuristic — flush the buffer when token budget reaches
    # half of max_tokens。 Matches HybridChunker default behaviour:
    # produce chunks at roughly 50-100% of max_tokens for retrieval。
    merge_flush_threshold = max(max_tokens // 2, 1)

    output: List[dict] = []
    pending_buf: List[str] = []
    pending_meta: Optional[dict] = None  # 首塊 meta
    pending_tokens = 0

    def _flush_pending():
        nonlocal pending_buf, pending_meta, pending_tokens
        if pending_buf:
            output.append({"text": "\n".join(pending_buf), **(pending_meta or {"headings": None, "page_no": None})})
            pending_buf = []
            pending_meta = None
            pending_tokens = 0

    for chunk in raw_chunks:
        # 接受 HierarchicalChunker 的 chunk 物件或裸字串(fallback 切分路徑用)
        text = (chunk.text if hasattr(chunk, "text") else chunk).strip()
        if not text:
            continue
        meta = _chunk_provenance(chunk)

        token_count = _count_tokens(tokenizer, text)

        if token_count > max_tokens:
            # Oversized — flush any pending small chunks first
            _flush_pending()
            for part in _split_by_lines(text, tokenizer, max_tokens, header=None):
                output.append({"text": part, **meta})  # 拆分段繼承源塊 meta
        elif token_count < merge_flush_threshold:
            # Small — accumulate, flush when buffer crosses threshold
            if not pending_buf:
                pending_meta = meta
            pending_buf.append(text)
            pending_tokens += token_count
            if pending_tokens >= merge_flush_threshold:
                _flush_pending()
        else:
            # Reasonable size — flush pending then add this chunk as-is
            _flush_pending()
            output.append({"text": text, **meta})

    _flush_pending()
    return output


def docling_convert_once(
    file_path: str,
    file_name: str,
    max_tokens: int = 512,
    tokenizer: Optional[str] = None,
    progress_cb: Optional[Any] = None,
) -> tuple[str, List[dict]]:
    """一次 Docling 解析，同時回傳全文 + 分塊記錄(BL-05:含 headings/page_no)

    解決原本 docling_load_as_text + docling_load_and_chunk 重複解析的問題，
    將 PDF 解析時間從 2 次 → 1 次。

    Args:
        file_path: Path to the document file
        file_name: Original file name
        max_tokens: Maximum tokens per chunk
        tokenizer: HuggingFace tokenizer name
        progress_cb: ``(stage, done, total)`` 頁級解析進度回報(可選)。
            PDF 走 ("loading", 已完成頁, 總頁數) — OCR 重的檔案終於有進度條;
            分頁式格式以外(docx 等)不回報計數,行為不變。

    Returns:
        (full_text, chunk_records) — 全文 Markdown + 分塊記錄
            ``[{"text", "headings", "page_no"}, ...]``(引用溯源,BL-05)
    """
    from docling.chunking import HierarchicalChunker

    try:
        # 1. Convert once（使用 singleton converter，模型已預載）
        converter = get_converter()

        # 頁級進度(觀察者,見 _install_page_progress_patch):
        # 分母用 pymupdf 秒算;算不出(非 PDF)就只報 done,前端顯示純 stage
        if progress_cb is not None:
            _install_page_progress_patch()
            _page_progress_tls.ctx = {
                "done": 0,
                "total": _pdf_page_count(file_path),
                "cb": progress_cb,
            }

        # FileStorage 把檔案落地成 UUID(無副檔名)。docling 的 _guess_format
        # 走「magic bytes → extension → content sniff」三段瀑布,純文字格式
        # (.md / .html / .csv / .vtt / .latex / .adoc)都沒 magic bytes,
        # 沒副檔名直接 fallback 失敗回 None,觸發
        # "Input document <uuid> with format None does not match any allowed format"。
        # 包成 DocumentStream + 帶原始 file_name,讓 _guess_format 從 file_name
        # 的副檔名走第二段瀑布,不靠 magic bytes 也認得出 .md 等格式。
        path_obj = Path(file_path)
        # H2: 只把 convert() 包進推論鎖,檔案讀取留在鎖外以縮短持鎖時間。
        if path_obj.suffix == "" and Path(file_name).suffix != "":
            from docling.datamodel.base_models import DocumentStream
            from io import BytesIO
            with path_obj.open("rb") as f:
                stream = DocumentStream(name=file_name, stream=BytesIO(f.read()))
            with DOCLING_INFER_LOCK:
                result = converter.convert(source=stream)
        else:
            with DOCLING_INFER_LOCK:
                result = converter.convert(source=file_path)
        doc = result.document

        # 2. Export full text as Markdown
        full_text = doc.export_to_markdown()
        logger.debug(f"Docling loaded {file_name}: {len(full_text)} chars")

        # 3. Chunk via HierarchicalChunker (fast structural pre-split) +
        #    per-chunk tokenizer refinement (see helpers above)。 We
        #    deliberately bypass HybridChunker — its slide-window
        #    splitter on a single huge HierarchicalChunker output (xlsx
        #    一張 5000-row 表 = 一塊巨大 chunk) runs the tokenizer in
        #    O(N_total tokens) which crosses both the 600s watchdog and
        #    the 1800s per-file timeout。 Our path tokenizes per-chunk,
        #    keeping each call bounded by chunk size — minutes → seconds
        #    on 巨表 input,with identical robustness guarantees。
        hf_tok = get_hf_tokenizer(tokenizer)

        raw_chunks = list(HierarchicalChunker().chunk(dl_doc=doc))
        texts = _refine_chunks_for_token_budget(raw_chunks, hf_tok, max_tokens)

        logger.info(
            f"Docling processed {file_name}: {len(texts)} chunks "
            f"(max_tokens={max_tokens})"
        )
        return full_text, texts

    except Exception as e:
        # 偵測常見的「文件本身有問題」錯誤,給出對 user 更明確的訊息。
        # 這些錯誤不是 server bug,而是檔案需要特殊處理。
        err_msg = str(e).lower()
        if "incorrect password" in err_msg or "encrypted" in err_msg:
            logger.error(
                f"❌ {file_name} is password-protected. "
                f"Remove password before uploading. "
                f"(原始錯誤: {e})"
            )
            raise ValueError(
                f"PDF is password-protected: '{file_name}'. "
                f"請先解密後再上傳。"
            ) from e
        if "is not valid" in err_msg or "corrupt" in err_msg:
            logger.error(f"❌ {file_name} is corrupted or unreadable: {e}")
            raise ValueError(
                f"File appears corrupted or unreadable: '{file_name}'."
            ) from e
        logger.error(f"Docling processing failed for {file_name}: {e}")
        raise
    finally:
        # 頁級進度 TLS 清理 — 同 thread 的下一個檔案不能吃到殘留 context
        if getattr(_page_progress_tls, "ctx", None) is not None:
            _page_progress_tls.ctx = None

