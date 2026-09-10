
"""BL-21 — import 環自動守門:src/ 全模組零循環依賴(A→B→A 永久阻斷)。

守兩級,都必須零環:
1. 頂層 import(import-time 環 → 啟動直接炸)
2. 含函式內 lazy import(執行期耦合環 — lazy 常被拿來「繞開」import-time
   環,那只是把炸點延後,架構上仍是 A↔B)

歷史:M6/H5 重構消除了 fastmcp↔adapter↔domain 的所有環(2026-08 實測兩級
皆零);此測試把該狀態釘死 — 新增任何回環(包括用 lazy import 藏起來的)
CI 立即紅,並印出完整環路徑。TYPE_CHECKING 塊排除(純型別,無執行期耦合)。
"""

import ast
from collections import defaultdict
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"


def _modules() -> dict:
    return {
        ".".join(p.relative_to(_SRC.parent).with_suffix("").parts): p
        for p in _SRC.rglob("*.py")
    }


def _edges_of(path: Path, dotted: str, mods: dict, include_lazy: bool) -> set:
    def resolve(name):
        if name in mods:
            return name
        if f"{name}.__init__" in mods:
            return f"{name}.__init__"
        return None

    out = set()

    class V(ast.NodeVisitor):
        def visit_If(self, node):
            if "TYPE_CHECKING" in ast.unparse(node.test):
                for n in node.orelse:
                    self.visit(n)
                return
            self.generic_visit(node)

        def visit_FunctionDef(self, node):
            if include_lazy:
                self.generic_visit(node)

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Import(self, node):
            for a in node.names:
                r = resolve(a.name)
                if r:
                    out.add(r)

        def visit_ImportFrom(self, node):
            if node.module:
                r = resolve(node.module)
                if r:
                    out.add(r)
                else:
                    for a in node.names:
                        r2 = resolve(f"{node.module}.{a.name}")
                        if r2:
                            out.add(r2)

    V().visit(ast.parse(path.read_text(encoding="utf-8")))
    out.discard(dotted)
    return out


def _find_cycles(graph: dict) -> list:
    WHITE, GRAY, BLACK = 0, 1, 2
    color = defaultdict(int)
    cycles = []

    def dfs(u, stack):
        color[u] = GRAY
        stack.append(u)
        for v in graph.get(u, ()):
            if color[v] == GRAY:
                cycles.append(stack[stack.index(v):] + [v])
            elif color[v] == WHITE:
                dfs(v, stack)
        stack.pop()
        color[u] = BLACK

    for m in graph:
        if color[m] == 0:
            dfs(m, [])
    return cycles


def _src_cycles(include_lazy: bool) -> list:
    mods = _modules()
    graph = {m: _edges_of(p, m, mods, include_lazy) for m, p in mods.items()}
    return _find_cycles(graph)


# ---- 演算法自檢(守門不是擺設:自捏的環必須抓得到)---------------------------

def test_cycle_detector_catches_planted_cycle():
    graph = {"a": {"b"}, "b": {"c"}, "c": {"a"}, "d": {"a"}}
    cycles = _find_cycles(graph)
    assert cycles, "偵測器抓不到自捏的 a→b→c→a 環"


def test_cycle_detector_clean_dag_passes():
    assert _find_cycles({"a": {"b", "c"}, "b": {"c"}, "c": set()}) == []


# ---- 真實 src/ 斷言 -----------------------------------------------------------

def test_no_import_time_cycles():
    """頂層 import 零環 — 有環啟動即炸,這是最硬的不變式。"""
    cycles = _src_cycles(include_lazy=False)
    assert not cycles, "import-time 環:\n" + "\n".join(" → ".join(c) for c in cycles)


def test_no_runtime_lazy_import_cycles():
    """含 lazy import 也零環 — lazy 不是繞開環的許可證,只是把 A↔B 藏進函式。"""
    cycles = _src_cycles(include_lazy=True)
    assert not cycles, "執行期(lazy)環:\n" + "\n".join(" → ".join(c) for c in cycles)


def test_graph_is_nontrivial():
    """防空轉:圖必須真的解析到大量模組與邊(不是掃了個寂寞)。"""
    mods = _modules()
    assert len(mods) > 30, f"只解析到 {len(mods)} 個模組,src 掃描可能壞了"
    graph = {m: _edges_of(p, m, mods, True) for m, p in mods.items()}
    n_edges = sum(len(v) for v in graph.values())
    assert n_edges > 50, f"只解析到 {n_edges} 條邊,import 解析可能壞了"
