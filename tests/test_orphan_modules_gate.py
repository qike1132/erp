# tests/test_orphan_modules_gate.py
"""回归锁：孤儿门禁必须 (a) 在真仓库上通过、(b) 仍抓得住真死模块。

背景（2026-10-03，P0-8 基线的回归修复）
--------------------------------------
P2 批次的 mypy 白名单扩容（144 → 370）之后，CI 门禁 ``scripts/check_orphan_modules.py``
在 main 上**变红**：断言 A 报 6 个 ``__init__.py`` 条目「全仓零入边」。

根因不在白名单，而在扫描器的边集口径：``import a.b.c`` 在运行期必然执行
``a/__init__.py`` 与 ``a/b/__init__.py``，但保守图只记 ``a.b.c`` 这一条边 —— 于是
「子模块被导入、父包必然被导入」的包**永远拿不到入边**，白名单一旦填 ``__init__.py``
就必然误报（与断言 B 明确「包不是孤儿候选」的既有设计也不一致）。
修法是在边集上补祖先包（``_with_parent_packages``），不改断言语义。

本文件锁两件事，缺一不可
------------------------
1. **行为锁**：真门禁在真仓库上 exit 0（走子进程，与 CI 同一调用形态）；
2. **反证锁**：补边**不得**削弱断言 A —— 合成的「零入边白名单条目」必须仍被判 FAIL。
   没有第 2 条，任何人都能把门禁改成恒绿而测试全过。

关于 import 被测脚本：``check_orphan_modules`` 在 import 期只定义常量与函数（无
stdout 包装、无文件写入、无 DB 连接），故可直接 import 其私有函数做单测；
``file_size_gate`` 那类有 import 期副作用的门禁才必须整程走子进程。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "scripts" / "check_orphan_modules.py"

sys.path.insert(0, str(ROOT / "scripts"))
import check_orphan_modules as com  # 路径就位后才能导入


@pytest.fixture(scope="module")
def repo_graph() -> com._Graph:
    """真仓库的导入图（整图只建一次；约 6 秒）。"""
    return com._build_graph(com._iter_py_files())


def test_gate_exits_zero_on_repo() -> None:
    """CI 契约：门禁在真仓库上必须 exit 0（允许剩 WARN，WARN 不阻断）。"""
    proc = subprocess.run(
        [sys.executable, str(GATE)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_every_whitelisted_module_has_an_in_edge(repo_graph: com._Graph) -> None:
    """断言 A 的口径：白名单条目全部有入边（修复前是 362/368，6 个 __init__.py 误报）。"""
    failures, _prod_gap, dangling, no_edge, whitelist = com._whitelist_check(repo_graph)
    assert not dangling, f"白名单有悬挂条目（指向不存在的模块）：{dangling}"
    assert not no_edge, f"白名单里仍有零入边模块：{no_edge}"
    assert not failures, failures
    assert len(whitelist) >= 360, f"白名单条目数异常偏少：{len(whitelist)}"


def test_parent_packages_backfilled_only_when_known() -> None:
    """补边只补 known 内真实存在的祖先包，不凭字符串想象模块。"""
    known = frozenset({"a", "a.b", "a.b.c", "x"})
    assert com._with_parent_packages({"a.b.c"}, known) == {"a", "a.b", "a.b.c"}
    assert com._with_parent_packages({"x"}, known) == {"x"}
    # 祖先不在 known 里就不补（该包在仓库里根本不存在）
    assert com._with_parent_packages({"a.b.c"}, frozenset({"a.b.c"})) == {"a.b.c"}
    # 深链一次补齐
    deep = frozenset({"p", "p.q", "p.q.r", "p.q.r.s"})
    assert com._with_parent_packages({"p.q.r.s"}, deep) == {"p", "p.q", "p.q.r", "p.q.r.s"}
    # 空集不产生边
    assert com._with_parent_packages(set(), known) == set()


def test_gate_still_catches_a_genuinely_dead_whitelisted_module(tmp_path, monkeypatch) -> None:
    """反证：补边之后，「零入边」的白名单条目必须**仍**被判 FAIL（门禁没被改成恒绿）。

    用合成图 + 临时白名单（只把 ``MYPY_INI`` 指过去），不碰真 mypy.ini。
    dead：零入边 → 必须进 no_edge 且进 failures；
    alive：有入边且生产可达 → 一条 failure 都不该有。
    """
    ini = tmp_path / "mypy.ini"
    ini.write_text("files = probe/dead.py, probe/alive.py\n", encoding="utf-8")
    monkeypatch.setattr(com, "MYPY_INI", ini)

    graph = com._Graph(
        known={"probe.dead", "probe.alive"},
        path_by_module={},
        is_package={"probe.dead": False, "probe.alive": False},
        is_test={"probe.dead": False, "probe.alive": False},
        indegree={"probe.dead": 0, "probe.alive": 1},
        prod_reachable={"probe.alive"},
        all_reachable={"probe.alive"},
        missing_roots=[],
    )
    failures, _prod_gap, dangling, no_edge, whitelist = com._whitelist_check(graph)

    assert whitelist == ["probe/dead.py", "probe/alive.py"], whitelist
    assert not dangling, f"合成白名单不该有悬挂条目：{dangling}"
    assert any("probe.dead" in item for item in no_edge), f"真死模块没被抓到：{no_edge}"
    assert any("probe.dead" in item for item in failures), failures
    assert not any("probe.alive" in item for item in failures), failures
