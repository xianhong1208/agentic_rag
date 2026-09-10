
"""BL-02 — ASR 評測跑分:對任一 AsrProvider 跑 golden transcripts,產出 CER 表。

用法:
    uv run --no-sync python scripts/run_asr_eval.py                 # config 的 provider
    uv run --no-sync python scripts/run_asr_eval.py --provider openai-compatible
    uv run --no-sync python scripts/run_asr_eval.py --baseline evals/baselines/asr_xxx.json

素材(見 evals/README.md):
    evals/asr/audio/<name>.{wav,mp3,m4a,aac,ogg,flac}
    evals/asr/golden_transcripts/<name>.txt     # 人工校對繁中全文

指標:CER(字元錯誤率,去標點空白)、簡體字比率(繁中驗收 ≈0)、
幻覺 pattern 命中數(audio_defense)、耗時。
評測對象 = provider 原始輸出(不含前導靜音裁切/幻覺過濾 — 那是生產防禦層,
幻覺數在此以「過濾器命中計數」呈現,供模型間比較)。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

AUDIO_DIR = REPO / "evals" / "asr" / "audio"
GOLDEN_DIR = REPO / "evals" / "asr" / "golden_transcripts"
BASELINE_DIR = REPO / "evals" / "baselines"
_AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", help="覆蓋 config 的 rag.asr.provider")
    ap.add_argument("--baseline", help="與既有基線 JSON 比較")
    ap.add_argument("--config", default="config/config.yaml")
    args = ap.parse_args()

    pairs = []
    for f in sorted(AUDIO_DIR.iterdir()) if AUDIO_DIR.is_dir() else []:
        if f.suffix.lower() in _AUDIO_EXTS:
            g = GOLDEN_DIR / f"{f.stem}.txt"
            if g.is_file():
                pairs.append((f, g))
            else:
                print(f"⚠️  {f.name} 無對應 golden_transcripts/{f.stem}.txt — 跳過")
    if not pairs:
        print("❌ 無評測素材。請放置:")
        print(f"   {AUDIO_DIR.relative_to(REPO)}/<name>.wav|mp3|m4a|aac|ogg|flac")
        print(f"   {GOLDEN_DIR.relative_to(REPO)}/<name>.txt(人工校對繁中全文)")
        return 2

    from src.config.config_manager import Config
    Config.set_config(args.config)
    from src.config.model import AsrConfig
    from src.domain.rag.asr_provider import create_asr_provider
    from src.domain.rag.audio_defense import _filter_whisper_hallucinations
    from evals.metrics import cer, simplified_char_ratio

    asr_cfg = getattr(getattr(Config.get_config_model(), "rag", None), "asr", None)
    if args.provider:
        base = asr_cfg.model_dump() if asr_cfg else {}
        base["provider"] = args.provider
        asr_cfg = AsrConfig(**base)
    provider = create_asr_provider(asr_cfg)
    provider_name = asr_cfg.provider if asr_cfg else "docling-whisper"
    if not provider.available():
        print(f"❌ provider '{provider_name}' 不可服務(模型/端點未就緒)")
        return 2

    rows = []
    for audio, golden in pairs:
        ref = golden.read_text(encoding="utf-8")
        t0 = time.perf_counter()
        result = provider.transcribe(audio_path=str(audio), file_name=audio.name)
        elapsed = time.perf_counter() - t0
        _, n_halluc = _filter_whisper_hallucinations(result.text)
        rows.append({
            "file": audio.name,
            "cer": round(cer(ref, result.text), 4),
            "simplified_ratio": round(simplified_char_ratio(result.text), 4),
            "hallucination_matches": n_halluc,
            "elapsed_s": round(elapsed, 1),
            "ref_chars": len(ref),
            "hyp_chars": len(result.text),
            # 全文入基線:事後可做誤差歸因(如「假設後掛 s2twp 重算 CER」
            # 隔離簡繁字形 vs 真字錯)而不用重跑轉錄
            "ref": ref.strip(),
            "hyp": result.text.strip(),
        })
        print(f"  {audio.name}: CER={rows[-1]['cer']:.2%} 簡體率={rows[-1]['simplified_ratio']:.2%} "
              f"幻覺={n_halluc} {elapsed:.1f}s")

    summary = {
        "provider": provider_name,
        "date": date.today().isoformat(),
        "avg_cer": round(sum(r["cer"] for r in rows) / len(rows), 4),
        "avg_simplified_ratio": round(sum(r["simplified_ratio"] for r in rows) / len(rows), 4),
        "total_hallucinations": sum(r["hallucination_matches"] for r in rows),
        "files": rows,
    }
    out = BASELINE_DIR / f"asr_{provider_name}_{date.today().isoformat()}.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n== {provider_name} ==  avg CER {summary['avg_cer']:.2%} | "
          f"簡體率 {summary['avg_simplified_ratio']:.2%} | 幻覺 {summary['total_hallucinations']}")
    print(f"基線寫入:{out.relative_to(REPO)}")

    if args.baseline:
        base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        d = summary["avg_cer"] - base["avg_cer"]
        print(f"vs {base['provider']}({base['date']}):CER {base['avg_cer']:.2%} → "
              f"{summary['avg_cer']:.2%}({'+' if d >= 0 else ''}{d:.2%})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
