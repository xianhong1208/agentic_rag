# 缺陷報告範本 (Defect Report Template)

>
> 用法:複製到 `docs/testing/defect-reports/DEF-<YYYY>-<序號>.md`。一份缺陷一個檔。

---

# DEF-<YYYY>-<序號>:<缺陷標題>

| 欄位 | 內容 |
|------|------|
| **缺陷編號** | DEF-<YYYY>-<序號> |
| **狀態** | Open / In Progress / Fixed / Won't Fix / Deferred |
| **嚴重度 (Severity)** | Blocker / Critical / Major / Minor / Trivial |
| **優先級 (Priority)** | P0 / P1 / P2 / P3 |
| **發現階段** | 靜態分析 / 單元 / 整合 / 系統 / UAT / 程式審查 |
| **對應需求 / 測試** | REQ-xxx / `tests/test_xxx.py::...` |
| **回報者 / 日期** | <name> / <YYYY-MM-DD> |
| **指派給** | <owner> |

## 1. 環境
<版本、分支、DB、GPU/裝置、相關設定。>

## 2. 前置條件
<重現前需要的狀態 / 資料 / 登入身分。>

## 3. 重現步驟 (Steps to Reproduce)
1. …
2. …
3. …

## 4. 預期結果 (Expected)
<依需求應有的行為。>

## 5. 實際結果 (Actual)
<實際觀察到的行為。>

## 6. 佐證 (Evidence)
<測試輸出、system logs、截圖、堆疊追蹤。附 `logs/` 相關片段。>

## 7. 根因分析 (Root Cause,如已知)
<問題來源;是程式錯誤、需求變更未同步、環境問題等。>

## 8. 處置 / 修復 (Resolution)
<修法、對應 commit / MR、回歸測試。>
