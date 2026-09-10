
"""格式冒煙實測 — 白名單裡的每種可程式生成格式,真走 docling 解析取回內容。

「能支援什麼檔案都要試過才寫上去」(2026-09-02):每種格式生成最小樣本
(含哨兵字串)→ DocumentConverter.convert → 斷言哨兵在輸出裡。抓的是
「白名單收了但解析器依賴缺失」這類靜默壞(實例:odt 家族缺 odfdo、
ott/ots/otp 官方列了但 backend 打不開 — 都是這套實測抓到的)。

放 integration(需 docling 解析器 + LibreOffice;不需 DB/GPU 模型 —
覆蓋的都是純解析器格式)。PDF/圖片(OCR 模型)與音訊(whisper)不在此:
前者由既有部署驗證,後者由 BL-02 ASR 評測集負責。
"""

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

SENT = "哨兵內容SENTINEL"

_SOFFICE = shutil.which("soffice")


@pytest.fixture(scope="module")
def samples(tmp_path_factory):
    """生成全部可程式構造的最小樣本;LibreOffice 在才生成 legacy/範本變體。"""
    S = tmp_path_factory.mktemp("fmt")

    def w(name, text):
        (S / name).write_text(text, encoding="utf-8")

    # 純解析器文字家族
    w("t.md", f"# 標題\n\n{SENT}\n")
    w("t.qmd", f"---\ntitle: x\n---\n\n{SENT}\n")
    w("t.rmd", f"---\ntitle: x\n---\n\n{SENT}\n")
    for ext in ("adoc", "asciidoc", "asc"):
        w(f"t.{ext}", f"= T\n\n{SENT}\n")
    w("t.html", f"<html><body><p>{SENT}</p></body></html>")
    w("t.htm", f"<html><body><p>{SENT}</p></body></html>")
    w("t.xhtml", f'<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><body><p>{SENT}</p></body></html>')
    for ext in ("tex", "latex"):
        w(f"t.{ext}", f"\\documentclass{{article}}\\begin{{document}}{SENT}\\end{{document}}")
    w("t.vtt", f"WEBVTT\n\n00:00.000 --> 00:02.000\n{SENT}\n")
    w("t.eml", f"From: a@b.c\nTo: d@e.f\nSubject: test\nContent-Type: text/plain; charset=utf-8\n\n{SENT}\n")

    # Office Open XML 家族(python-docx / openpyxl 生成;變體同構改名)
    import docx as _docx
    d = _docx.Document(); d.add_paragraph(SENT); d.save(S / "t.docx")
    for ext in ("dotx", "docm", "dotm"):
        shutil.copy(S / "t.docx", S / f"t.{ext}")
    import openpyxl
    wb = openpyxl.Workbook(); wb.active["A1"] = SENT; wb.save(S / "t.xlsx")
    shutil.copy(S / "t.xlsx", S / "t.xlsm")

    # epub(最小 zip)
    with zipfile.ZipFile(S / "t.epub", "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr("OEBPS/content.opf", '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>t</dc:title><dc:identifier id="id">x</dc:identifier><dc:language>zh</dc:language></metadata><manifest><item id="c" href="c.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="c"/></spine></package>')
        z.writestr("OEBPS/c.xhtml", f'<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><body><p>{SENT}</p></body></html>')

    # OpenDocument(最小 ODF;需 odfdo — 依賴缺失時這裡就會紅)
    def odf(name, mime, body):
        with zipfile.ZipFile(S / name, "w") as z:
            z.writestr("mimetype", mime, compress_type=zipfile.ZIP_STORED)
            z.writestr("META-INF/manifest.xml", f'<?xml version="1.0"?><manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2"><manifest:file-entry manifest:full-path="/" manifest:media-type="{mime}"/><manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/></manifest:manifest>')
            z.writestr("content.xml", body)
    _T = '<?xml version="1.0"?><office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" office:version="1.2"><office:body>{}</office:body></office:document-content>'
    odf("t.odt", "application/vnd.oasis.opendocument.text",
        _T.format(f'<office:text><text:p>{SENT}</text:p></office:text>'))
    odf("t.ods", "application/vnd.oasis.opendocument.spreadsheet",
        _T.format(f'<office:spreadsheet><table:table table:name="S"><table:table-row><table:table-cell office:value-type="string"><text:p>{SENT}</text:p></table:table-cell></table:table-row></table:table></office:spreadsheet>'))
    odf("t.odp", "application/vnd.oasis.opendocument.presentation",
        _T.format(f'<office:presentation><draw:page draw:name="p1"><draw:frame><draw:text-box><text:p>{SENT}</text:p></draw:text-box></draw:frame></draw:page></office:presentation>'))

    # Legacy Office(需 soffice;沒裝就略過那批案)
    if _SOFFICE:
        def conv(to, src):
            subprocess.run([_SOFFICE, "--headless", "--convert-to", to, str(S / src),
                            "--outdir", str(S)], capture_output=True, timeout=120)
        conv("doc", "t.docx"); conv("dot", "t.docx")
        conv("xls", "t.xlsx"); conv("xlt", "t.xlsx")
        conv("ppt", "t.odp"); conv("pot", "t.odp"); conv("pps", "t.odp")
        # pptx 家族:soffice 產 pptx,巨集/放映變體同構改名(potx 實測打不開,不收)
        conv("pptx", "t.odp"); conv("ppsx", "t.odp"); conv("pptm", "t.odp")
        if (S / "t.pptx").exists():
            for ext in ("potm", "ppsm"):
                shutil.copy(S / "t.pptx", S / f"t.{ext}")
    return S


@pytest.fixture(scope="module")
def converter(itest_db):
    # itest_db 只作為 opt-in 閘門(RAG_RUN_DB_ITESTS);converter 本身不用 DB
    from docling.document_converter import DocumentConverter
    return DocumentConverter()


_PURE_PARSER_EXTS = [
    "md", "qmd", "rmd", "adoc", "asciidoc", "asc",
    "html", "htm", "xhtml", "tex", "latex", "vtt", "eml",
    "docx", "dotx", "docm", "dotm", "xlsx", "xlsm",
    "epub", "odt", "ods", "odp",
]
_LEGACY_EXTS = ["doc", "dot", "xls", "xlt", "ppt", "pot", "pps",
                "pptx", "ppsx", "pptm", "potm", "ppsm"]


@pytest.mark.parametrize("ext", _PURE_PARSER_EXTS)
def test_pure_parser_format(samples, converter, ext):
    text = converter.convert(str(samples / f"t.{ext}")).document.export_to_markdown()
    assert SENT in text, f".{ext} 解析結果不含哨兵內容"


@pytest.mark.skipif(not _SOFFICE, reason="LibreOffice(soffice)未安裝")
@pytest.mark.parametrize("ext", _LEGACY_EXTS)
def test_legacy_office_format(samples, converter, ext):
    f = samples / f"t.{ext}"
    assert f.exists(), f"soffice 轉檔未產出 t.{ext}"
    text = converter.convert(str(f)).document.export_to_markdown()
    assert SENT in text, f".{ext} 解析結果不含哨兵內容"


# ---- BL-05:真 docling chunk 物件的引用溯源抽取 -------------------------------
# 單測(test_chunk_refine.py)用假 chunk 釘契約;這裡用**真** docling 輸出
# 驗證 meta 形狀假設(meta.headings / doc_items[].prov[].page_no)沒走樣 —
# docling 升版若改 chunk schema,這兩案會紅。

class _LenTok:
    def encode(self, text, add_special_tokens=False):
        return list(text)


def test_chunk_records_carry_headings_md(samples, converter):
    """md 經真 HierarchicalChunker → 記錄 headings 非空(# 標題)。"""
    from docling.chunking import HierarchicalChunker
    from src.domain.rag.docling_loader import _refine_chunks_for_token_budget

    doc = converter.convert(str(samples / "t.md")).document
    chunks = list(HierarchicalChunker().chunk(doc))
    recs = _refine_chunks_for_token_budget(chunks, _LenTok(), 512)
    assert recs, "md 解析後無 chunk 記錄"
    assert any(r["headings"] for r in recs), \
        "真 docling chunk 的 meta.headings 未進記錄(schema 走樣?)"


def test_chunk_records_carry_page_no_pdf(samples, converter):
    """PDF 經真 chunker → 記錄 page_no 非 None(prov 鏈)。"""
    import fitz
    from docling.chunking import HierarchicalChunker
    from src.domain.rag.docling_loader import _refine_chunks_for_token_budget

    pdf_path = samples / "t.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72, 72), "SENTINEL provenance text for BL-05")
        pdf.save(str(pdf_path))

    doc = converter.convert(str(pdf_path)).document
    chunks = list(HierarchicalChunker().chunk(doc))
    recs = _refine_chunks_for_token_budget(chunks, _LenTok(), 512)
    assert recs, "PDF 解析後無 chunk 記錄"
    assert any(r["page_no"] == 1 for r in recs), \
        "真 docling chunk 的 prov.page_no 未進記錄(schema 走樣?)"
