# TC-db-bootstrap:DB URL 解析 測試案例


| 項目 | 內容 |
|------|------|
| 對應規格 | [SPEC-db-bootstrap](../specs/SPEC-db-bootstrap.md) |
| 測試層級 | 單元(僅 `_parse_db_url`;連線類函式屬整合測試,不在此) |
| 測試腳本 | `tests/test_db_bootstrap.py` |

---

## TC-db-bootstrap-01:標準 URL 完整解析

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-db-bootstrap-01 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `postgresql://alice:s3cret@db.example.com:5433/ragdb` |
| **測試步驟** | 1. 呼叫 `_parse_db_url` |
| **預期結果** | `{"user": "alice", "password": "s3cret", "host": "db.example.com", "port": 5433, "dbname": "ragdb"}` |
| **實作** | `tests/test_db_bootstrap.py::test_parse_standard_url` |

## TC-db-bootstrap-02:缺 port 補預設 5432

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-db-bootstrap-02 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `postgresql://alice:pw@localhost/ragdb` |
| **測試步驟** | 1. 呼叫 `_parse_db_url` |
| **預期結果** | `port` == 5432、`host` == `"localhost"` |
| **實作** | `tests/test_db_bootstrap.py::test_parse_url_without_port_defaults_5432` |

## TC-db-bootstrap-03:百分比編碼帳密原樣保留(現行行為快照)

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-db-bootstrap-03 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `postgresql://u%40ser:p%40ss%3A1@db.host:6543/mydb` |
| **測試步驟** | 1. 呼叫 `_parse_db_url` |
| **預期結果** | `user` == `"u%40ser"`、`password` == `"p%40ss%3A1"`(**不**解碼為 `u@ser` / `p@ss:1`);host/port 正確 |
| **實作** | `tests/test_db_bootstrap.py::test_parse_url_percent_encoded_credentials_not_decoded` |

> 疑似缺口:下游 psycopg2 需要解碼後的帳密,密碼含特殊字元的部署會登入失敗;
> 詳見 SPEC-db-bootstrap 第 4 節備註。若修正為 `unquote`,本 TC 需同步改寫。

## TC-db-bootstrap-04:無帳密 URL

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-db-bootstrap-04 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `postgresql://localhost:5432/ragdb` |
| **測試步驟** | 1. 呼叫 `_parse_db_url` |
| **預期結果** | `user` / `password` 為 `None`;`dbname` == `"ragdb"`;不拋錯 |
| **實作** | `tests/test_db_bootstrap.py::test_parse_url_without_credentials` |

## TC-db-bootstrap-05:dbname 去除前導斜線

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-db-bootstrap-05 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `postgresql://u:p@h:5432/agentic_rag` |
| **測試步驟** | 1. 呼叫 `_parse_db_url` |
| **預期結果** | `dbname` == `"agentic_rag"`,不以 `/` 開頭 |
| **實作** | `tests/test_db_bootstrap.py::test_parse_url_strips_leading_slash_from_dbname` |

## TC-db-bootstrap-06:無 path 時 dbname 為空字串

| 欄位 | 內容 |
|------|------|
| **對應需求** | REQ-db-bootstrap-05 |
| **層級** | 單元 |
| **前置條件** | 無 |
| **測試輸入** | `postgresql://u:p@h:5432` |
| **測試步驟** | 1. 呼叫 `_parse_db_url` |
| **預期結果** | `dbname` == `""` |
| **實作** | `tests/test_db_bootstrap.py::test_parse_url_without_path_gives_empty_dbname` |
