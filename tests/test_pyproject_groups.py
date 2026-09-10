
"""Guard tests — PyTorch dependency-group 三份清單一致性(PEP 735 + uv)。

背景:torch 依 GPU 走 dependency group(cuda / cpu / rocm-r713 / rocm-r714),
一個 group 要正確運作,得同時出現在三個地方:
  (1) [dependency-groups]              —— 宣告 torch 三件套版本
  (2) [tool.uv] conflicts             —— 互斥守門(漏加 → 兩組 torch 互相覆蓋，uv 不警告)
  (3) [tool.uv.sources]               —— 把 torch/torchvision/torchaudio 指到對的 index

pyproject 檔頭自陳「conflicts 這份清單是唯一的守門，漏加 uv 不會警告」——
這個測試就是把那個「唯一守門」自動化,免得下次新增 ROCm 版本又漏一處。
純解析 pyproject.toml,零外部依賴。

跑法:cd agentic_rag && uv run --no-sync pytest tests/test_pyproject_groups.py -v
"""

import re
import tomllib
from pathlib import Path

import pytest

_TORCH_STACK = ("torch", "torchvision", "torchaudio")


def _load_pyproject() -> dict:
    path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with path.open("rb") as f:
        return tomllib.load(f)


def _dep_name(spec: str) -> str:
    """從 dep 字串取套件名:'torch[device-all]==2.11.0+rocm7.13.0' → 'torch'。"""
    m = re.match(r"^\s*([A-Za-z0-9._-]+)", spec)
    return m.group(1).lower() if m else ""


def _torch_groups(data: dict) -> set[str]:
    """回傳「有宣告 torch」的 group —— 只有這些 group 需要互斥 + source mapping。

    非 torch group(未來若新增 dev/lint 之類)不會被這個測試綁死。
    """
    groups = data.get("dependency-groups", {})
    return {
        name
        for name, specs in groups.items()
        if any(_dep_name(s) == "torch" for s in specs if isinstance(s, str))
    }


def _conflict_groups(data: dict) -> set[str]:
    result: set[str] = set()
    for cluster in data["tool"]["uv"].get("conflicts", []):
        for item in cluster:
            if "group" in item:
                result.add(item["group"])
    return result


def _source_groups(data: dict, package: str) -> set[str]:
    entries = data["tool"]["uv"].get("sources", {}).get(package, [])
    return {e["group"] for e in entries if "group" in e}


@pytest.fixture(scope="module")
def pyproject() -> dict:
    return _load_pyproject()


def test_torch_groups_present(pyproject):
    """前置:確實解析到 torch group(否則後面斷言會空跑而假綠)。"""
    groups = _torch_groups(pyproject)
    assert groups, "沒有解析到任何宣告 torch 的 dependency-group"
    # 目前應至少涵蓋這四個;新增別的不會讓測試失敗,但少了既有的要當回事
    assert {"cuda", "cpu"} <= groups, f"預期 cuda/cpu 為 torch group,實得 {groups}"


def test_every_torch_group_in_conflicts(pyproject):
    """每個 torch group 都必須在互斥清單裡 —— 漏加會讓兩組 torch 同時裝進去互相覆蓋。"""
    torch_groups = _torch_groups(pyproject)
    conflict_groups = _conflict_groups(pyproject)
    missing = torch_groups - conflict_groups
    assert not missing, (
        f"torch group {sorted(missing)} 不在 [tool.uv] conflicts 清單裡;"
        f"同時啟用會互相覆蓋且 uv 不會警告。請加進互斥清單。"
    )


def test_conflicts_only_reference_real_groups(pyproject):
    """反向:conflicts 不該引用不存在的 group(例如舊的 per-gfx 別名殘留)。"""
    declared = set(pyproject.get("dependency-groups", {}))
    stale = _conflict_groups(pyproject) - declared
    assert not stale, f"conflicts 引用了不存在的 group {sorted(stale)}(可能是刪 group 時漏清)"


@pytest.mark.parametrize("package", _TORCH_STACK)
def test_every_torch_group_has_source_mapping(pyproject, package):
    """torch/torchvision/torchaudio 三件套,每個 torch group 都要有 index source mapping。

    漏了 source mapping → 該套件改從預設 PyPI 解析,ROCm 的 +rocmX.Y.Z local
    version 在 PyPI 找不到 → sync 直接失敗(至少會當場爆,不會靜默走錯 index)。
    """
    torch_groups = _torch_groups(pyproject)
    mapped = _source_groups(pyproject, package)
    missing = torch_groups - mapped
    assert not missing, (
        f"{package} 缺少 group {sorted(missing)} 的 [tool.uv.sources] index 對應"
    )
