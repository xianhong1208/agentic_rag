
"""GPU pipeline 探針 — 在服務機驗證「索引時到底有沒有用 GPU」。

檢查三層(每層都可能靜默退 CPU;OCR 已統一 rapidocr torch backend,
不再有 onnxruntime 套件層要驗):
  ① torch 看不看得到 GPU(docling 的 use_cuda gate;ROCm 也走這裡)
  ② 服務同款 converter 建出來的 RapidOCR torch session 實際 device(呼叫層真相)
  ③ Layout/TableFormer 模型實際落在哪個 device

跑法:
    PYTHONPATH=. uv run --no-sync python scripts/probe_gpu_pipeline.py
"""

import sys


def main() -> int:
    problems = []

    # ① torch
    import torch
    cuda_ok = torch.cuda.is_available()
    name = torch.cuda.get_device_name(0) if cuda_ok else "-"
    print(f"① torch.cuda.is_available() = {cuda_ok}  ({torch.__version__}, {name})")
    if not cuda_ok:
        problems.append("torch 看不到 GPU → docling 全 pipeline 退 CPU(container --gpus?/driver?)")

    # ② 服務同款 converter → RapidOCR torch session 實際 device
    from src.config.config_manager import get_config
    get_config("config/config.yaml")
    from src.domain.rag.docling_loader import get_converter
    from docling.datamodel.base_models import InputFormat

    converter = get_converter()
    try:
        pdf_pipeline = converter._get_pipeline(InputFormat.PDF)
        ocr_model = getattr(pdf_pipeline, "ocr_model", None)
        if ocr_model is None:
            print("② pipeline 內找不到 ocr_model(OCR 未啟用?)")
            problems.append("OCR stage 不在 pipeline(檢查 ocr_enabled)")
        else:
            found = False
            reader = ocr_model.reader
            for part_name in ("text_det", "text_cls", "text_rec"):
                part = getattr(reader, part_name, None)
                sess = getattr(getattr(part, "session", None), "session", None) or getattr(part, "session", None)
                dev = getattr(sess, "device", None)
                if dev is None:
                    continue
                found = True
                on_gpu = "cuda" in str(dev).lower()
                print(f"② RapidOCR {part_name}: device={dev}  {'✅GPU' if on_gpu else '❌CPU'}")
                if not on_gpu:
                    problems.append(
                        f"OCR {part_name} 落在 CPU(EngineConfig.torch.use_cuda 未生效"
                        f"或 accelerator device 判定為 cpu)"
                    )
            if not found:
                print("② 無法內省 RapidOCR torch sessions(rapidocr 版本結構不同)— 改用 nvidia-smi/rocm-smi 觀察")
    except Exception as e:
        print(f"② converter 內省失敗: {type(e).__name__}: {e}")

    # ③ Layout 模型 device
    try:
        layout = getattr(pdf_pipeline, "layout_model", None)
        if layout is not None:
            dev = None
            for attr in ("device", "_device"):
                dev = dev or getattr(layout, attr, None)
            inner = getattr(layout, "layout_predictor", None) or getattr(layout, "model", None)
            if dev is None and inner is not None:
                dev = getattr(inner, "device", None) or getattr(inner, "_device", None)
            print(f"③ Layout model device = {dev}")
            if dev is not None and "cuda" not in str(dev).lower():
                problems.append("Layout 模型落在 CPU")
    except Exception as e:
        print(f"③ layout 內省失敗: {type(e).__name__}: {e}")

    print()
    if problems:
        print("❌ 發現問題:")
        for p in problems:
            print(f"   - {p}")
        return 1
    print("✅ 三層全部在 GPU 上")
    return 0


if __name__ == "__main__":
    sys.exit(main())
