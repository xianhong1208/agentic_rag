# 缺陷報告索引 (Defect Reports)


一份缺陷一個檔,命名 `DEF-<YYYY>-<序號>.md`,範本見 [../templates/DEFECT_REPORT_TEMPLATE.md](../templates/DEFECT_REPORT_TEMPLATE.md)。

| 編號 | 標題 | 嚴重度 | 狀態 |
|------|------|--------|------|
| [DEF-2026-001](DEF-2026-001.md) | `_parse_db_url` 未對帳密做 percent-decoding | Major | Open |
| [DEF-2026-002](DEF-2026-002.md) | 例外類別以 truthiness 判斷 `folder_id`,`0` 被誤當未提供 | Minor | Open |
| [DEF-2026-003](DEF-2026-003.md) | `${VAR:-default}` 環境變數展開未實作,與 README 宣稱不符 | Minor | Open |
| [DEF-2026-004](DEF-2026-004.md) | `_load_config` 吞掉 FileNotFoundError,設定檔路徑錯誤時靜默啟動 | Minor | Open |

**出場準則**(TEST_PLAN 第 4 節):合併 / 發布前,本索引不得有 Open 的 Blocker / Critical。
