
"""首頁 (landing page) 路由。"""

import base64
import html
import re
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["Index"])

_LOGO_PATH = Path(__file__).resolve().parents[3] / "assets" / "logo.png"


@lru_cache(maxsize=1)
def _logo_data_uri() -> str:
    """將 logo 檔讀成可內嵌於 HTML 的 base64 data URI（結果會被快取）。

    Returns:
        `data:image/png;base64,...` 字串；找不到 logo 檔時回傳空字串。
    """
    try:
        data = base64.b64encode(_LOGO_PATH.read_bytes()).decode("ascii")
        return f"data:image/png;base64,{data}"
    except FileNotFoundError:
        return ""


# 輕量 Markdown → HTML 轉換器
def _inline(text: str) -> str:
    """套用行內 Markdown 語法（程式碼、粗體、連結）。

    Args:
        text: 已經過 HTML escape 的文字。

    Returns:
        套用行內語法後的 HTML 片段。
    """
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


_TABLE_SEP_RE = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$")


def _split_table_row(row: str) -> list[str]:
    """Split `| a | b | c |` into ['a', 'b', 'c']. Tolerates missing edge pipes."""
    s = row.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _try_consume_table(lines: list[str], i: int) -> tuple[str | None, int]:
    """嘗試把 lines[i:] 解析成 markdown table(GFM 風格)。

    需 lines[i] 是 header row、lines[i+1] 是 `|---|---|` separator,後續連續的
    `| ... |` row 都吃進來。不像 table 就 return (None, 0) 讓 caller 走原邏輯。

    Args:
        lines: markdown 全文按行切的 list。
        i: 起始 index。

    Returns:
        ``(html, consumed)`` ─ html 是組好的 ``<table>...</table>``;
        ``consumed`` 是吃掉的行數。不是 table → ``(None, 0)``。
    """
    if i + 1 >= len(lines):
        return None, 0
    header_raw = lines[i].strip()
    sep_raw = lines[i + 1].strip()
    if "|" not in header_raw or not _TABLE_SEP_RE.match(sep_raw):
        return None, 0
    headers = _split_table_row(header_raw)
    if not headers:
        return None, 0
    rows: list[list[str]] = []
    j = i + 2
    while j < len(lines):
        line = lines[j].strip()
        if not line or "|" not in line:
            break
        rows.append(_split_table_row(line))
        j += 1

    parts = ["<table>", "<thead><tr>"]
    parts.extend(f"<th>{_inline(html.escape(h))}</th>" for h in headers)
    parts.append("</tr></thead>")
    parts.append("<tbody>")
    for row in rows:
        parts.append("<tr>")
        parts.extend(f"<td>{_inline(html.escape(c))}</td>" for c in row)
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "\n".join(parts), j - i


def markdown_to_html(md: str) -> str:
    """將 Markdown 轉成 HTML，支援標題、清單、程式碼區塊、表格、粗體、連結與分隔線。

    Args:
        md: Markdown 原始字串。

    Returns:
        轉換後的 HTML 字串（內容均經 HTML escape）。
    """
    lines = md.split("\n")
    out: list[str] = []
    para: list[str] = []
    list_type: str | None = None
    i = 0

    def flush_para():
        if para:
            text = " ".join(para).strip()
            if text:
                out.append(f"<p>{_inline(text)}</p>")
            para.clear()

    def close_list():
        nonlocal list_type
        if list_type:
            out.append(f"</{list_type}>")
            list_type = None

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 程式碼區塊 ```
        if stripped.startswith("```"):
            flush_para(); close_list()
            i += 1
            buf = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(html.escape(lines[i]))
                i += 1
            out.append("<pre><code>" + "\n".join(buf) + "</code></pre>")
            i += 1
            continue

        # 空行
        if not stripped:
            flush_para(); close_list()
            i += 1
            continue

        # 表格(必須在水平分隔線/段落 fallback 之前;`|---|---|` 對 hr 來說也可能像分隔線)
        table_html, consumed = _try_consume_table(lines, i)
        if table_html is not None:
            flush_para(); close_list()
            out.append(table_html)
            i += consumed
            continue

        # 水平分隔線
        if re.match(r"^(-{3,}|\*{3,})$", stripped):
            flush_para(); close_list()
            out.append("<hr>")
            i += 1
            continue

        # 標題 #..######
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            flush_para(); close_list()
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline(html.escape(m.group(2)))}</h{level}>")
            i += 1
            continue

        # 無序清單 - / *
        m = re.match(r"^[-*]\s+(.*)$", stripped)
        if m:
            flush_para()
            if list_type != "ul":
                close_list(); out.append("<ul>"); list_type = "ul"
            out.append(f"<li>{_inline(html.escape(m.group(1)))}</li>")
            i += 1
            continue

        # 有序清單 1. 2. ...
        m = re.match(r"^\d+\.\s+(.*)$", stripped)
        if m:
            flush_para()
            if list_type != "ol":
                close_list(); out.append("<ol>"); list_type = "ol"
            out.append(f"<li>{_inline(html.escape(m.group(1)))}</li>")
            i += 1
            continue

        # 一般段落
        para.append(html.escape(stripped))
        i += 1

    flush_para(); close_list()
    return "\n".join(out)


# 頁面樣板
_PAGE = """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%%TITLE%%</title>
%%FAVICON%%
<style>
:root{--brand:#0a4d8c;--brand-dark:#063a6b;--bg:#f5f7fa;--card:#fff;--text:#1f2933;--muted:#6b7280;--border:#e5e7eb;}
*{box-sizing:border-box;}
body{margin:0;font-family:-apple-system,"Segoe UI","PingFang TC","Microsoft JhengHei",sans-serif;background:var(--bg);color:var(--text);line-height:1.65;}
.hero{background:linear-gradient(135deg,var(--brand),var(--brand-dark));color:#fff;padding:52px 24px 60px;text-align:center;}
.badge{display:inline-block;background:rgba(255,255,255,.2);padding:3px 12px;border-radius:999px;font-size:.85rem;letter-spacing:.5px;}
.hero h1{margin:10px 0 6px;font-size:2.1rem;}
.hero p{margin:8px auto 0;opacity:.92;max-width:560px;}
.actions{margin-top:26px;display:flex;gap:12px;justify-content:center;flex-wrap:wrap;}
.btn{display:inline-flex;align-items:center;gap:8px;padding:12px 22px;border-radius:8px;font-weight:600;text-decoration:none;transition:transform .05s,box-shadow .2s,background .2s;}
.btn-primary{background:#fff;color:var(--brand);box-shadow:0 2px 10px rgba(0,0,0,.18);}
.btn-primary:hover{transform:translateY(-1px);box-shadow:0 6px 18px rgba(0,0,0,.22);}
.btn-ghost{background:transparent;color:#fff;border:1px solid rgba(255,255,255,.6);}
.btn-ghost:hover{background:rgba(255,255,255,.14);}
.container{max-width:880px;margin:-32px auto 40px;padding:0 24px;}
.card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:32px 38px;box-shadow:0 6px 28px rgba(0,0,0,.07);}
.card h1,.card h2,.card h3{color:var(--brand-dark);}
.card h1{margin-top:8px;}
.card h2{border-bottom:1px solid var(--border);padding-bottom:6px;margin-top:30px;}
.card code{background:#eef2f7;padding:2px 6px;border-radius:4px;font-size:.9em;}
.card pre{background:#0f172a;color:#e2e8f0;padding:16px;border-radius:8px;overflow-x:auto;}
.card pre code{background:none;padding:0;color:inherit;}
.card a{color:var(--brand);}
.card table{border-collapse:collapse;width:100%;margin:14px 0;font-size:.95em;}
.card thead th{background:#eef2f7;color:var(--brand-dark);text-align:left;padding:8px 12px;border-bottom:2px solid var(--border);}
.card tbody td{padding:8px 12px;border-bottom:1px solid var(--border);vertical-align:top;}
.card tbody tr:hover{background:#f9fafb;}
.card tbody td code{background:#eef2f7;}
.footer{text-align:center;color:var(--muted);font-size:.85rem;padding:8px 24px 40px;}
.footer code{background:#e5e7eb;padding:2px 6px;border-radius:4px;}
.topbar{background:#fff;padding:8px 24px;text-align:center;border-bottom:1px solid var(--border);line-height:0;}
.topbar img{height:80px;width:auto;max-width:90%;vertical-align:middle;}
</style>
</head>
<body>
%%TOPBAR%%
  <div class="hero">
    <span class="badge">v%%VERSION%%</span>
    <h1>%%TITLE%%</h1>
    <p>%%DESC%%</p>
    <div class="actions">
      <a class="btn btn-primary" href="/docs">📘 API 文件 (Swagger)</a>
      <a class="btn btn-ghost" href="/health">❤ 健康檢查</a>
    </div>
  </div>
  <div class="container">
    <div class="card">
%%INSTRUCTIONS%%
    </div>
  </div>
  <div class="footer">
  </div>
</body>
</html>"""


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index(request: Request) -> HTMLResponse:
    """服務首頁：顯示服務名稱與版本、進入 /docs 的按鈕，以及 instructions 內容。

    Args:
        request: 進來的請求，用以取得 app 的 title/version/description 與 instructions。

    Returns:
        渲染後的首頁 HTMLResponse。
    """
    app = request.app
    title = getattr(app, "title", "MCP Service")
    version = getattr(app, "version", "0.0.0")
    description = getattr(app, "description", "") or "Agentic RAG MCP Service"

    instructions_md = getattr(app.state, "instructions", "") or ""
    instructions_html = markdown_to_html(instructions_md) if instructions_md else "<p>（尚未提供 instructions）</p>"

    logo = _logo_data_uri()
    topbar = f'  <div class="topbar"><img src="{logo}" alt="logo"></div>' if logo else ""
    favicon = f'<link rel="icon" type="image/png" href="{logo}">' if logo else ""

    page = (
        _PAGE
        .replace("%%FAVICON%%", favicon)
        .replace("%%TOPBAR%%", topbar)
        .replace("%%TITLE%%", html.escape(title))
        .replace("%%VERSION%%", html.escape(str(version)))
        .replace("%%DESC%%", html.escape(description))
        .replace("%%INSTRUCTIONS%%", instructions_html)
    )
    return HTMLResponse(content=page)
