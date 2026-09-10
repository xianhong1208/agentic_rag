
"""逐檔覆蓋率下限把關(coverage 的 fail_under 只管總體,無 per-file 門檻)。

用法(先跑出 coverage.json 再檢查):
    uv run --no-sync pytest --cov=src --cov-report=json:reports/coverage.json
    uv run --no-sync python scripts/check_coverage_floor.py reports/coverage.json

規則:每個入統計的檔案 line coverage >= FLOOR(50%),違者列出並以非零退出。
omit 清單(pyproject [tool.coverage.run])管「哪些檔案入統計」;這裡管
「入了統計就不准擺爛」— 兩者相加:要嘛好好測,要嘛明列豁免理由,不准中間態。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

FLOOR = 50.0


def main() -> int:
    report = Path(sys.argv[1] if len(sys.argv) > 1 else "reports/coverage.json")
    if not report.is_file():
        print(f"❌ coverage json 不存在:{report}(先跑 pytest --cov-report=json:{report})")
        return 2

    data = json.loads(report.read_text(encoding="utf-8"))
    offenders = []
    for path, info in sorted(data.get("files", {}).items()):
        summary = info.get("summary", {})
        # 空檔(__init__ 等 0 statements)視為通過
        if summary.get("num_statements", 0) == 0:
            continue
        pct = summary.get("percent_covered", 0.0)
        if pct < FLOOR:
            offenders.append((pct, path, summary.get("num_statements", 0)))

    if offenders:
        print(f"❌ {len(offenders)} 檔低於逐檔下限 {FLOOR:.0f}%:")
        for pct, path, stmts in sorted(offenders):
            print(f"   {pct:5.1f}%  {path}  ({stmts} stmts)")
        print("   → 補測試,或(重外部依賴者)加進 pyproject omit 並附理由。")
        return 1

    total = data.get("totals", {}).get("percent_covered", 0.0)
    print(f"✅ 逐檔覆蓋率下限 {FLOOR:.0f}% 全數通過(總體 {total:.2f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
