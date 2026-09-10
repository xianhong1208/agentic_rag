# SPEC-db-bootstrap:DB URL 解析(bootstrap 前置)


| 項目 | 內容 |
|------|------|
| 模組 | `src/utils/db_bootstrap.py`(僅 `_parse_db_url`) |
| 對應測試 | `tests/test_db_bootstrap.py` |
| 版本 | feat/rag-robustness |
| 最後更新 | 2026-07-09 |

## 1. 目的與範圍

`db_bootstrap` 在啟動時確保目標 DB 存在、pgvector / pg_jieba extension 啟用、HNSW index 補齊。
本規格**只涵蓋純函式 `_parse_db_url(url) -> dict`**:把 SQLAlchemy 形式的
`postgresql://user:pwd@host:port/dbname` 拆成 psycopg2 連線參數 dict
(`user` / `password` / `host` / `port` / `dbname`)。

明確不在單元測試範圍(需真實 psycopg2 / SQLAlchemy 連線,屬整合測試):
`_database_exists`、`_create_database`、`_enable_extensions`、
`ensure_hnsw_for_table`、`_ensure_hnsw_indexes`、`ensure_database_ready`。

## 2. 功能需求 (Functional Requirements)

| 需求編號 | 需求描述 | 驗收準則(可觀察的行為) |
|---------|---------|------------------------|
| REQ-db-bootstrap-01 | 標準 URL 完整解析 | user / password / host / port / dbname 五欄位皆正確拆出 |
| REQ-db-bootstrap-02 | 缺 port 補預設 | URL 未帶 port 時 `port` = 5432 |
| REQ-db-bootstrap-03 | 百分比編碼帳密行為固定 | urlparse **不解碼** userinfo;`u%40ser` 原樣保留(現行行為快照,見第 4 節備註) |
| REQ-db-bootstrap-04 | 無帳密容忍 | URL 不含 userinfo 時 `user` / `password` 為 `None`,不拋錯 |
| REQ-db-bootstrap-05 | dbname 正規化 | path 前導 `/` 被去除;URL 無 path 時 dbname 為空字串 |

## 3. 非功能需求

- 純函式:不得發起任何連線或 I/O。

## 4. 邊界與例外 (Edge Cases & Errors)

| 情境 | 預期行為 |
|------|---------|
| URL 缺 port | 補 5432 |
| URL 缺 userinfo | user / password = `None` |
| URL 缺 path | dbname = `""` |
| 帳密含百分比編碼(`%40` 等) | 原樣保留,不 unquote |

> **備註(疑似缺口)**:`urllib.parse.urlparse` 的 `.username` / `.password` 不做
> percent-decoding,而下游 `psycopg2.connect` 需要的是**解碼後**的帳密。若部署環境
> 的 DB 密碼含 `@`、`:` 等需 percent-encode 的字元,bootstrap 連線將以編碼字串登入而
> 失敗。TC-db-bootstrap-03 以「現行行為快照」形式鎖定此行為;若未來修正(加
> `urllib.parse.unquote`),該測試需同步更新。

## 5. 相依與假設 (Dependencies & Assumptions)

- 模組頂層 import `psycopg2` / `sqlalchemy`(僅 import,不建立連線),測試環境已安裝即可。
- 其餘函式的驗證依 docs/testing/TEST_STRATEGY.md 歸屬整合測試,由部署環境腳本覆蓋。

## 6. 可追溯性矩陣 (Traceability)

| 需求 | 測試案例 | 測試腳本 |
|------|---------|---------|
| REQ-db-bootstrap-01 | TC-db-bootstrap-01 | `tests/test_db_bootstrap.py::test_parse_standard_url` |
| REQ-db-bootstrap-02 | TC-db-bootstrap-02 | `::test_parse_url_without_port_defaults_5432` |
| REQ-db-bootstrap-03 | TC-db-bootstrap-03 | `::test_parse_url_percent_encoded_credentials_not_decoded` |
| REQ-db-bootstrap-04 | TC-db-bootstrap-04 | `::test_parse_url_without_credentials` |
| REQ-db-bootstrap-05 | TC-db-bootstrap-05, TC-db-bootstrap-06 | `::test_parse_url_strips_leading_slash_from_dbname`、`::test_parse_url_without_path_gives_empty_dbname` |

(測試腳本欄位省略共同前綴 `tests/test_db_bootstrap.py`。)
