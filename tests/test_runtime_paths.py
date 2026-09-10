
"""Unit tests for src/utils/runtime_paths.py

不依賴 DB / vLLM / 任何外部服務 — 用 tmp_path + monkeypatch 模擬
dev / Nuitka onefile / standalone 各種部署場景的 env 與 sys 狀態。
目錄名一律帶 uuid,確保不會誤中真實 python bin 目錄 / /app 下的同名目錄。
跑法:cd agentic_rag && uv run pytest tests/test_runtime_paths.py -v
"""

import shutil
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from src.utils.runtime_paths import resolve_base_dir, resolve_external_dir

_LINUX = sys.platform.startswith("linux")


def _unique_name() -> str:
    """產生不可能撞名的資源目錄名"""
    return f"res_{uuid4().hex}"


@pytest.fixture
def no_nuitka_env(monkeypatch):
    """確保測試起點沒有 Nuitka onefile 的 env 訊號"""
    monkeypatch.delenv("NUITKA_ONEFILE_PARENT", raising=False)


# ---------------------------------------------------------------------------
# resolve_external_dir
# ---------------------------------------------------------------------------

def test_external_dir_found_under_dev_root(tmp_path, no_nuitka_env):
    """dev 模式:dev_root/name 存在時應回傳該目錄(TC-runtime-paths-01)"""
    name = _unique_name()
    (tmp_path / name).mkdir()
    assert resolve_external_dir(name, dev_root=tmp_path) == tmp_path / name


def test_external_dir_returns_none_when_nowhere(tmp_path, no_nuitka_env):
    """所有候選位置都不存在時應回 None(TC-runtime-paths-02)"""
    assert resolve_external_dir(_unique_name(), dev_root=tmp_path) is None


def test_external_dir_ignores_plain_file(tmp_path, no_nuitka_env):
    """同名的一般檔案(非目錄)不算命中,應回 None(TC-runtime-paths-03)"""
    name = _unique_name()
    (tmp_path / name).write_text("not a dir")
    assert resolve_external_dir(name, dev_root=tmp_path) is None


def test_external_dir_sys_executable_beats_dev_root(tmp_path, monkeypatch, no_nuitka_env):
    """sys.executable 旁的目錄(standalone 部署)優先於 dev_root(TC-runtime-paths-04)"""
    name = _unique_name()
    bin_dir = tmp_path / "bin"
    (bin_dir / name).mkdir(parents=True)
    dev_root = tmp_path / "dev"
    (dev_root / name).mkdir(parents=True)
    monkeypatch.setattr(sys, "executable", str(bin_dir / "app.bin"))
    assert resolve_external_dir(name, dev_root=dev_root) == bin_dir / name


def test_external_dir_rejects_tmp_onefile_executable(tmp_path, monkeypatch, no_nuitka_env):
    """sys.executable 落在 /tmp/onefile_* 時應拒用,fallback 到 dev_root(TC-runtime-paths-05)"""
    name = _unique_name()
    onefile_dir = Path(tempfile.mkdtemp(prefix="onefile_", dir="/tmp"))
    try:
        (onefile_dir / name).mkdir()  # 就算解壓目錄裡有 bundled copy 也要被拒
        monkeypatch.setattr(sys, "executable", str(onefile_dir / "app.bin"))
        dev_root = tmp_path / "dev"
        (dev_root / name).mkdir(parents=True)
        assert resolve_external_dir(name, dev_root=dev_root) == dev_root / name
    finally:
        shutil.rmtree(onefile_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# resolve_base_dir
# ---------------------------------------------------------------------------

def test_base_dir_dev_mode_returns_dev_root(tmp_path, no_nuitka_env):
    """非 compiled(plain Python)模式應直接回 dev_root(TC-runtime-paths-06)"""
    assert resolve_base_dir(dev_root=tmp_path) == tmp_path


@pytest.mark.skipif(not _LINUX, reason="依賴 /proc/self/exe(Linux only)")
def test_base_dir_frozen_uses_real_executable_dir(tmp_path, monkeypatch, no_nuitka_env):
    """sys.frozen(compiled)時應回 /proc/self/exe 所在目錄,而非 dev_root(TC-runtime-paths-07)"""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    expected = Path("/proc/self/exe").resolve().parent
    assert resolve_base_dir(dev_root=tmp_path) == expected
    assert resolve_base_dir(dev_root=tmp_path) != tmp_path


@pytest.mark.skipif(not _LINUX, reason="依賴 /proc(Linux only)")
def test_base_dir_nuitka_parent_pid_resolves_parent_exe(tmp_path, monkeypatch):
    """NUITKA_ONEFILE_PARENT 指向存活 process 時應回其執行檔目錄(TC-runtime-paths-08)"""
    monkeypatch.setenv("NUITKA_ONEFILE_PARENT", "self")  # /proc/self/exe 必存在
    expected = Path("/proc/self/exe").resolve().parent
    assert resolve_base_dir(dev_root=tmp_path) == expected


@pytest.mark.skipif(not _LINUX, reason="依賴 /proc/self/exe(Linux only)")
def test_base_dir_invalid_nuitka_pid_falls_back_to_self_exe(tmp_path, monkeypatch):
    """NUITKA_ONEFILE_PARENT 是死 PID 時仍視為 compiled,fallback 到 /proc/self/exe(TC-runtime-paths-09)"""
    monkeypatch.setenv("NUITKA_ONEFILE_PARENT", "999999999")
    expected = Path("/proc/self/exe").resolve().parent
    assert resolve_base_dir(dev_root=tmp_path) == expected
    assert resolve_base_dir(dev_root=tmp_path) != tmp_path


@pytest.mark.skipif(not _LINUX, reason="依賴 /proc/self/exe(Linux only)")
def test_base_dir_nuitka_compiled_marker_detected(tmp_path, monkeypatch, no_nuitka_env):
    """__main__.__compiled__(Nuitka 標記)也應觸發 compiled 路徑(TC-runtime-paths-10)"""
    main_mod = sys.modules["__main__"]
    monkeypatch.setattr(main_mod, "__compiled__", True, raising=False)
    expected = Path("/proc/self/exe").resolve().parent
    assert resolve_base_dir(dev_root=tmp_path) == expected


@pytest.mark.skipif(not _LINUX, reason="依賴 /proc(Linux only)")
def test_external_dir_nuitka_parent_candidate_walked(tmp_path, monkeypatch):
    """NUITKA_ONEFILE_PARENT=self:候選鏈 ① 有走過(parent exe 旁無資源時
    仍正確 fallback 到 dev_root)(TC-runtime-paths-11)"""
    name = _unique_name()
    monkeypatch.setenv("NUITKA_ONEFILE_PARENT", "self")  # /proc/self/exe 必存在
    (tmp_path / name).mkdir()
    assert resolve_external_dir(name, dev_root=tmp_path) == tmp_path / name


def test_external_dir_dead_nuitka_pid_skipped(tmp_path, monkeypatch):
    """NUITKA_ONEFILE_PARENT 是死 PID:① 靜默跳過不炸,fallback 正常(TC-runtime-paths-12)"""
    name = _unique_name()
    monkeypatch.setenv("NUITKA_ONEFILE_PARENT", "999999999")
    (tmp_path / name).mkdir()
    assert resolve_external_dir(name, dev_root=tmp_path) == tmp_path / name


def test_base_dir_non_linux_compiled_uses_sys_executable(tmp_path, monkeypatch, no_nuitka_env):
    """compiled + 非 Linux(② /proc 不可用)→ ③ sys.executable 目錄(TC-runtime-paths-13)"""
    import src.utils.runtime_paths as rp
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(rp.sys, "platform", "win32")
    expected = Path(sys.executable).resolve().parent
    assert resolve_base_dir(dev_root=tmp_path) == expected
