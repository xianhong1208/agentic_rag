
"""ASR golden transcript 草稿產生器(BL-02 前置)。

從零逐字打 golden 全文不現實 — 先用 ASR 產草稿到 evals/asr/drafts/,
人工聽音檔校對後搬進 golden_transcripts/(工作流見 evals/README.md)。

用法:
    uv run --no-sync python scripts/make_asr_drafts.py                  # whisper(預設)
    uv run --no-sync python scripts/make_asr_drafts.py --provider fireredasr
        # → drafts/<stem>.fireredasr.txt(第二意見,與 whisper 版並排對照;
        #   兩版分歧處 = 校對時優先聽的段落)

⚠️ drafts/ 內容是機器輸出,絕不能直接搬進 golden_transcripts/ 拿去算分
(CER 會變成在跟產草稿的模型自己的錯誤比)。
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--provider", default="docling-whisper",
                    choices=["docling-whisper", "fireredasr"])
    ap.add_argument("--force", action="store_true", help="覆蓋既有草稿")
    args = ap.parse_args()

    audio_dir = Path("evals/asr/audio")
    out_dir = Path("evals/asr/drafts")
    out_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(f for f in audio_dir.iterdir()
                   if f.suffix.lower() in AUDIO_EXTS)
    if not files:
        print("evals/asr/audio/ 沒有音檔 — 先放素材(見 evals/README.md)")
        return 2

    from src.config.model import AsrConfig
    from src.domain.rag.asr_provider import create_asr_provider

    provider = create_asr_provider(AsrConfig(provider=args.provider))
    if not provider.available():
        print(f"provider '{args.provider}' 不可用(模型/權重未就緒)")
        return 2

    # whisper 版當主草稿(無後綴);其他 provider 加後綴當第二意見
    suffix = "" if args.provider == "docling-whisper" else f".{args.provider}"

    for f in files:
        dst = out_dir / f"{f.stem}{suffix}.txt"
        if dst.exists() and not args.force:
            print(f"skip(已存在,--force 覆蓋): {dst.name}")
            continue
        t0 = time.time()
        r = provider.transcribe(audio_path=str(f), file_name=f.name)
        dst.write_text(r.text.strip() + "\n", encoding="utf-8")
        print(f"{f.name}: {len(r.text)} 字, {time.time() - t0:.0f}s → {dst.name}")

    print("\n草稿完成 — 人工校對後搬進 evals/asr/golden_transcripts/(檔名去後綴)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
