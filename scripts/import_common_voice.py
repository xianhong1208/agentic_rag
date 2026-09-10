
"""Common Voice(zh-TW)→ ASR 評測素材匯入(BL-02)。

從 Mozilla Data Collective 下載的 Common Voice tar.gz 抽樣 N 段已驗證
clip,落地成本 repo 評測格式:
    evals/asr/audio/cv_<clip名>.mp3
    evals/asr/golden_transcripts/cv_<clip名>.txt   ← 人工驗證句子,免校對

用法:
    # Mozilla Data Collective 全包(tsv 在 tar 內):
    uv run --no-sync python scripts/import_common_voice.py <tar.gz 路徑> [--n 200] [--seed 42]
    # HF 鏡像(fsicoli/common_voice_*:audio shard .tar + transcript .tsv 分開):
    uv run --no-sync python scripts/import_common_voice.py <shard.tar> --tsv <test.tsv>

- 抽樣定死 seed → 可重現;重跑會先清掉舊的 cv_* 檔
- CC0-1.0 授權(公有領域),素材照舊不進 repo(gitignore)
- 只取 validated(有人工驗證)的 clip;TSV 自動偵測
  (欄位含 path + sentence 的 validated*.tsv 優先,否則第一個符合的 tsv)
"""

import argparse
import csv
import random
import sys
import tarfile
from pathlib import Path


def find_tsv(tar: tarfile.TarFile):
    """挑轉錄 TSV:validated 優先;回 (member, clips 目錄前綴)。"""
    tsvs = [m for m in tar.getmembers() if m.name.endswith(".tsv")]
    tsvs.sort(key=lambda m: (0 if "validated" in Path(m.name).name else 1, m.name))
    for m in tsvs:
        f = tar.extractfile(m)
        if f is None:
            continue
        head = f.readline().decode("utf-8", errors="replace")
        cols = head.rstrip("\n").split("\t")
        if "path" in cols and "sentence" in cols:
            return m, cols
    return None, None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("tarball", help="Common Voice tar(.gz) 路徑")
    ap.add_argument("--tsv", help="外部轉錄 TSV(HF 鏡像的 audio/transcript 分裝時用)")
    ap.add_argument("--n", type=int, default=200, help="抽樣 clip 數(預設 200)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    audio_dir = Path("evals/asr/audio")
    golden_dir = Path("evals/asr/golden_transcripts")
    golden_dir.mkdir(parents=True, exist_ok=True)

    # 清舊 cv_* 樣本(重抽時不混批)
    for old in list(audio_dir.glob("cv_*")) + list(golden_dir.glob("cv_*")):
        old.unlink()

    with tarfile.open(args.tarball, "r:*") as tar:
        if args.tsv:
            lines = Path(args.tsv).read_text(encoding="utf-8").splitlines()
            reader = csv.DictReader(lines, delimiter="\t")
            print(f"轉錄表:{args.tsv}(外部)")
        else:
            tsv_member, _ = find_tsv(tar)
            if tsv_member is None:
                print("tar 內找不到含 path+sentence 欄位的 .tsv(HF 鏡像請帶 --tsv)")
                return 2
            print(f"轉錄表:{tsv_member.name}")
            f = tar.extractfile(tsv_member)
            reader = csv.DictReader(
                (line.decode("utf-8", errors="replace") for line in f), delimiter="\t")

        rows = []
        for row in reader:
            s = (row.get("sentence") or "").strip()
            p = (row.get("path") or "").strip()
            if s and p:
                rows.append((p, s))
        print(f"可用 clip:{len(rows)}")
        if not rows:
            return 2

        random.Random(args.seed).shuffle(rows)
        picked = rows[: args.n]

        # clip 成員以檔名索引(全包版在 */clips/、HF shard 在 <shard>/ 平鋪)
        by_name = {}
        for m in tar.getmembers():
            if m.isfile() and Path(m.name).suffix.lower() in {".mp3", ".wav", ".flac", ".m4a", ".ogg"}:
                by_name[Path(m.name).name] = m

        done = 0
        for p, s in picked:
            m = by_name.get(Path(p).name)
            if m is None:
                continue
            stem = "cv_" + Path(p).stem
            with open(audio_dir / (stem + Path(p).suffix), "wb") as out:
                out.write(tar.extractfile(m).read())
            (golden_dir / (stem + ".txt")).write_text(s + "\n", encoding="utf-8")
            done += 1

    print(f"落地 {done}/{len(picked)} 段 → evals/asr/audio/ + golden_transcripts/")
    print("下一步:uv run --no-sync python scripts/run_asr_eval.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
