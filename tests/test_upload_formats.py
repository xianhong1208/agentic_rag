
"""上傳格式政策的回歸測試 — 白名單與解析路由的一致性

格式支援 v2(docling 2.119):legacy Office(.doc/.xls/.ppt,經 LibreOffice)
+ Outlook .msg + 純文字家族(yaml/xml/conf/log)。核心不變式:
**白名單裡的每個副檔名都必須有明確的解析路徑**(docling 或純文字直讀),
不允許落入 SimpleDirectoryReader fallback 把二進制當文字硬讀(.doc 亂碼事故
的根因,見 a64641d)。
跑法:cd agentic_rag && uv run pytest tests/test_upload_formats.py -v
"""

from db.filedb import FileDB
from src.domain.rag.docling_loader import DOCLING_EXTENSIONS

# 與 hierarchical_indexer.load_document_from_file 的 text_extensions 同步
_TEXT_EXTENSIONS = {".txt", ".text", ".json", ".csv", ".yaml", ".yml", ".xml", ".conf", ".log"}


def test_legacy_office_and_msg_allowed():
    """格式支援 v2:doc/xls/ppt/msg 在白名單(TC-upload-fmt-01)"""
    for ext in ("doc", "xls", "ppt", "msg"):
        assert ext in FileDB.ALLOWED_EXTENSIONS, f"{ext} 應在白名單"


def test_text_family_allowed():
    """純文字家族(yaml/yml/xml/conf/log)在白名單(TC-upload-fmt-02)"""
    for ext in ("yaml", "yml", "xml", "conf", "log"):
        assert ext in FileDB.ALLOWED_EXTENSIONS, f"{ext} 應在白名單"


def test_every_allowed_extension_has_a_parser_route():
    """不變式:白名單 ∖(docling ∪ 純文字)= 空集(TC-upload-fmt-03)

    任何只進白名單、沒有解析路徑的副檔名都會掉進 SimpleDirectoryReader
    fallback — 對二進制格式等於靜默索引亂碼。
    """
    routed = {e.lstrip(".") for e in DOCLING_EXTENSIONS} | {
        e.lstrip(".") for e in _TEXT_EXTENSIONS
    }
    orphans = FileDB.ALLOWED_EXTENSIONS - routed
    assert not orphans, f"這些副檔名沒有解析路徑,會索引亂碼: {orphans}"


def test_unsupported_formats_stay_rejected():
    """仍拒收的格式沒被誤放行(TC-upload-fmt-04)

    影片(webm/mkv/mp4)待 BL-22(需掛 docling VIDEO pipeline);
    可執行/壓縮檔永遠拒。"""
    for ext in ("webm", "mkv", "mp4", "exe", "zip", "pages"):
        assert ext not in FileDB.ALLOWED_EXTENSIONS, f"{ext} 不應在白名單"


def test_validate_rejects_disallowed_and_accepts_new(tmp_path):
    """_validate_file_content:新格式放行、未支援格式拒絕(TC-upload-fmt-05)"""
    import pytest
    ok = FileDB._validate_file_content(b"dummy", "letter.doc")
    assert ok["extension"] == "doc"
    ok = FileDB._validate_file_content(b"k: v", "settings.yaml")
    assert ok["extension"] == "yaml"
    with pytest.raises(ValueError):
        FileDB._validate_file_content(b"dummy", "movie.mp4")


def test_format_v3_official_parity():
    """格式 v3(docling 2.124 官網對標,TC-upload-fmt-06):
    音訊對齊官方 6 種;補 OpenDocument / epub / latex / eml / xlsm。
    (每個新格式的解析路由由 TC-03 不變式自動把關)"""
    for ext in ("m4a", "aac", "ogg", "flac"):          # 官方 audio 6 種(wav/mp3 已有)
        assert ext in FileDB.ALLOWED_EXTENSIONS, f"audio {ext} 應在白名單"
    for ext in ("odt", "ods", "odp", "epub", "tex", "eml", "xlsm"):
        assert ext in FileDB.ALLOWED_EXTENSIONS, f"{ext} 應在白名單"


def test_official_docling_format_parity():
    """程式化官網對標(TC-upload-fmt-07):docling FormatToExtensions 的每個
    非排除格式的每個副檔名都必須有解析路由(docling ∪ 純文字直讀)。
    docling 未來新增格式 → 此測試自動紅,對標永不過期。
    排除者必須在 _EXCLUDED_FORMATS 附理由 — 不允許無聲缺席。"""
    from docling.datamodel.base_models import InputFormat, FormatToExtensions

    _EXCLUDED_FORMATS = {
        "video": "BL-22:需掛 VIDEO pipeline(keyframe + ffmpeg 接線),非僅加副檔名",
        "xml_uspto": ".xml 歧義家族:泛用 .xml 已走純文字直讀,專業 XML 變體不自動路由",
        "xml_jats": "同 xml_uspto",
        "xml_xbrl": "同 xml_uspto",
        "xml_doclang": "docling 內部格式",
        "dclx": "docling 內部格式",
        "json_docling": ".json 已走純文字直讀",
        "mets_gbs": "tar.gz 壓縮包,不收壓縮檔",
        "boxnote": "Box 專有協作格式,無使用場景",
        "ebcdic": "大型主機編碼,無使用場景",
        "iwork_pages": "需 docling[format-iwork] extra 套件,未安裝",
    }
    # ext 級排除:官方映射列了、但**實測不過**的個別副檔名(格式本身收)
    _EXCLUDED_EXTS = {
        "ott": "2026-09-02 實測:docling odfdo backend 打不開 text-template(LibreOffice 真檔亦 fail)",
        "ots": "同 ott(spreadsheet-template)",
        "otp": "同 ott(presentation-template)",
        "potx": "2026-09-02 實測:docling MsPowerpointDocument 打不開 potx 範本(pptx/ppsx/pptm/potm/ppsm 皆 OK)",
    }
    routed = {e.lstrip(".") for e in DOCLING_EXTENSIONS} | {
        e.lstrip(".") for e in _TEXT_EXTENSIONS
    }
    missing = {}
    for fmt in InputFormat:
        if fmt.value in _EXCLUDED_FORMATS:
            continue
        gap = {e.lower() for e in FormatToExtensions.get(fmt, [])} - routed - set(_EXCLUDED_EXTS)
        if gap:
            missing[fmt.value] = sorted(gap)
    assert not missing, (
        f"docling 官方格式未對標(加進白名單,或進 _EXCLUDED_FORMATS/_EXCLUDED_EXTS 附理由):{missing}"
    )
