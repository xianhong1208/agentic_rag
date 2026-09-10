
"""Unit tests for src/storage/file_storage.py

不依賴 DB / vLLM / 任何外部服務 — 檔案系統操作全部導向 pytest tmp_path。
注意:模組 import 時就會執行 _resolve_storage_root() 決定 STORAGE_ROOT,
所以測試改用 monkeypatch 直接替換 FileStorage 的 class attribute,
而 _resolve_storage_root() 本身另以 env var 單獨測。
跑法:cd agentic_rag && uv run pytest tests/test_file_storage.py -v
"""

from pathlib import Path

import pytest

import src.storage.file_storage as fs_mod
from src.storage.file_storage import FileStorage, _resolve_storage_root, _validate_safe_name
from src.utils.runtime_paths import resolve_base_dir


@pytest.fixture
def storage_root(tmp_path, monkeypatch) -> Path:
    """把 FileStorage 的存儲根導向 tmp_path,測試不落地到真實 storage/"""
    monkeypatch.setattr(FileStorage, "STORAGE_ROOT", tmp_path / "storage")
    monkeypatch.setattr(FileStorage, "STORAGE_FILE_ROOT", tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# _validate_safe_name
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name",
    [
        "abc",
        "ABC-123_x",
        "report.pdf",
        "中文資料夾",
        "財報 2026.xlsx",
        "mixed中英-1.0",
    ],
)
def test_validate_safe_name_accepts_legal_names(name):
    """合法名稱(英數 / _-. / 空格 / 中文)應通過不拋錯(TC-file-storage-01)"""
    _validate_safe_name(name, "folder")  # 不應拋例外


def test_validate_safe_name_rejects_empty_string():
    """空字串應拋 ValueError(TC-file-storage-02)"""
    with pytest.raises(ValueError, match="cannot be empty"):
        _validate_safe_name("", "token")


@pytest.mark.parametrize("bad", [None, 123, 1.5, ["a"]])
def test_validate_safe_name_rejects_non_string(bad):
    """None / 非字串型別應拋 ValueError(TC-file-storage-03)"""
    with pytest.raises(ValueError):
        _validate_safe_name(bad, "token")


@pytest.mark.parametrize("bad", ["..", "../etc/passwd", "a..b", "a/../b"])
def test_validate_safe_name_rejects_dotdot_traversal(bad):
    """含 `..` 的 path traversal 名稱應拋 ValueError(TC-file-storage-04)"""
    with pytest.raises(ValueError, match="illegal path characters"):
        _validate_safe_name(bad, "folder")


@pytest.mark.parametrize("bad", ["a/b", "/abs", "a\\b", "\\\\share"])
def test_validate_safe_name_rejects_path_separators(bad):
    """含 `/` 或 `\\` 分隔符的名稱應拋 ValueError(TC-file-storage-05)"""
    with pytest.raises(ValueError, match="illegal path characters"):
        _validate_safe_name(bad, "folder")


@pytest.mark.parametrize("bad", [".hidden", ".env"])
def test_validate_safe_name_rejects_leading_dot(bad):
    """開頭為 `.` 的名稱應拋 ValueError(TC-file-storage-06)"""
    with pytest.raises(ValueError, match="illegal path characters"):
        _validate_safe_name(bad, "file")


@pytest.mark.parametrize("bad", ["a*b", "a?b", "a$b", "a:b", "a|b", "🚀rocket", "a\tb"])
def test_validate_safe_name_rejects_special_characters(bad):
    """白名單外的特殊字元 / emoji 應拋 ValueError(TC-file-storage-07)"""
    with pytest.raises(ValueError, match="illegal characters"):
        _validate_safe_name(bad, "file")


# ---------------------------------------------------------------------------
# _resolve_storage_root
# ---------------------------------------------------------------------------

def test_resolve_storage_root_env_override(tmp_path, monkeypatch):
    """設定 MIRAG_STORAGE_ROOT 時應直接採用該路徑(TC-file-storage-08)"""
    custom = tmp_path / "custom_root"
    monkeypatch.setenv("MIRAG_STORAGE_ROOT", str(custom))
    assert _resolve_storage_root() == custom.resolve()


def test_resolve_storage_root_defaults_to_base_dir(monkeypatch):
    """未設 env 時應回 resolve_base_dir(dev 模式 = 專案根目錄)(TC-file-storage-09)"""
    monkeypatch.delenv("MIRAG_STORAGE_ROOT", raising=False)
    monkeypatch.delenv("NUITKA_ONEFILE_PARENT", raising=False)
    project_root = Path(fs_mod.__file__).resolve().parents[2]
    assert _resolve_storage_root() == resolve_base_dir(dev_root=project_root)


# ---------------------------------------------------------------------------
# FileStorage.save_file / read_file
# ---------------------------------------------------------------------------

def test_save_file_writes_content_and_returns_relative_path(storage_root):
    """save_file 應寫入檔案並回傳 storage/ 開頭的相對路徑(TC-file-storage-10)"""
    rel = FileStorage.save_file("tok1", "月報", "file-uuid-1", b"hello bytes")
    assert rel == "storage/tok1/月報/file-uuid-1"
    saved = storage_root / "storage" / "tok1" / "月報" / "file-uuid-1"
    assert saved.read_bytes() == b"hello bytes"


def test_save_file_illegal_folder_name_raises_ioerror(storage_root):
    """save_file 收到非法 folder_name 時 ValueError 被包裝成 IOError(TC-file-storage-11)"""
    with pytest.raises(IOError, match="Failed to save file"):
        FileStorage.save_file("tok1", "../escape", "fid", b"x")
    # 不應在 tmp 根外建立任何東西
    assert not (storage_root / "escape").exists()


def test_read_file_returns_saved_content(storage_root):
    """read_file 以 save_file 回傳的相對路徑應讀回原內容(TC-file-storage-12)"""
    rel = FileStorage.save_file("tok1", "docs", "fid-2", b"\x00\x01binary")
    assert FileStorage.read_file(rel) == b"\x00\x01binary"


def test_read_file_missing_raises_file_not_found(storage_root):
    """read_file 讀不存在的路徑應拋 FileNotFoundError(TC-file-storage-13)"""
    with pytest.raises(FileNotFoundError):
        FileStorage.read_file("storage/tok1/docs/ghost")


# ---------------------------------------------------------------------------
# FileStorage.delete_file / delete_folder
# ---------------------------------------------------------------------------

def test_delete_file_success_returns_true(storage_root):
    """delete_file 刪除存在的檔案應回 True 且檔案消失(TC-file-storage-14)"""
    rel = FileStorage.save_file("tok1", "docs", "fid-3", b"x")
    assert FileStorage.delete_file(rel) is True
    assert not (storage_root / rel).exists()


def test_delete_file_missing_returns_false(storage_root):
    """delete_file 刪除不存在的檔案應回 False 不拋錯(TC-file-storage-15)"""
    assert FileStorage.delete_file("storage/tok1/docs/ghost") is False


def test_delete_folder_removes_recursively(storage_root):
    """delete_folder 應遞迴刪除整個資料夾並回 True(TC-file-storage-16)"""
    FileStorage.save_file("tok1", "docs", "fid-a", b"1")
    FileStorage.save_file("tok1", "docs", "fid-b", b"2")
    assert FileStorage.delete_folder("tok1", "docs") is True
    assert not (storage_root / "storage" / "tok1" / "docs").exists()


def test_delete_folder_missing_returns_false(storage_root):
    """delete_folder 對不存在的資料夾應回 False(TC-file-storage-17)"""
    assert FileStorage.delete_folder("tok1", "ghost") is False


def test_delete_folder_illegal_name_raises_value_error(storage_root):
    """delete_folder 收到非法名稱應直接拋 ValueError(不吞成 False)(TC-file-storage-18)"""
    with pytest.raises(ValueError):
        FileStorage.delete_folder("tok1", "../../etc")


# ---------------------------------------------------------------------------
# FileStorage.rename_folder
# ---------------------------------------------------------------------------

def test_rename_folder_success(storage_root):
    """rename_folder 成功改名應回 True,舊路徑消失、新路徑保留檔案(TC-file-storage-19)"""
    FileStorage.save_file("tok1", "old_name", "fid", b"data")
    assert FileStorage.rename_folder("tok1", "old_name", "new_name") is True
    base = storage_root / "storage" / "tok1"
    assert not (base / "old_name").exists()
    assert (base / "new_name" / "fid").read_bytes() == b"data"


def test_rename_folder_source_missing_returns_false(storage_root):
    """rename_folder 舊資料夾不存在應回 False(TC-file-storage-20)"""
    assert FileStorage.rename_folder("tok1", "ghost", "new") is False


def test_rename_folder_target_exists_returns_false(storage_root):
    """rename_folder 目標資料夾已存在應回 False 且不覆蓋(TC-file-storage-21)"""
    FileStorage.save_file("tok1", "src_dir", "fid1", b"1")
    FileStorage.save_file("tok1", "dst_dir", "fid2", b"2")
    assert FileStorage.rename_folder("tok1", "src_dir", "dst_dir") is False
    base = storage_root / "storage" / "tok1"
    assert (base / "src_dir" / "fid1").exists()
    assert (base / "dst_dir" / "fid2").exists()


# ---------------------------------------------------------------------------
# FileStorage.resolve_path
# ---------------------------------------------------------------------------

def test_resolve_path_joins_relative_under_file_root(storage_root):
    """resolve_path 應把 DB 相對路徑接在 STORAGE_FILE_ROOT 下(TC-file-storage-22)"""
    assert FileStorage.resolve_path("storage/t/f/id") == storage_root / "storage" / "t" / "f" / "id"


def test_resolve_path_absolute_input_kept_as_is(storage_root):
    """resolve_path 收到絕對路徑時 Path 語意會丟棄左側、原樣回傳(TC-file-storage-23)"""
    assert FileStorage.resolve_path("/abs/x/y") == Path("/abs/x/y")


def test_read_file_not_found_raises():
    """讀不存在的檔案:log + 原樣 raise FileNotFoundError(不吞、不轉型)。"""
    from src.storage.file_storage import FileStorage
    import pytest as _pytest
    with _pytest.raises(FileNotFoundError):
        FileStorage.read_file("storage/no-such-token/no-such-file-xyz")
