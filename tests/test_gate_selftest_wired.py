"""门禁自检「必须真有人跑」的棘轮（2026-10-17 审计 TEST 区 / 批次 8）。

`scripts/_selftest_gate.py` 是跨门禁的语义自检：N+1 判定不退化（真 N+1 必报、
`for ... in iterable` 的查询不得报、就地标注必须带理由、白名单 `file::func` 生效、
僵尸键必报）、子进程中文 stderr 必须按 UTF-8 读回、语法错误文件与无效路径必须发
WARN 而不是静默 PASS。

问题在于它长期**没有任何调用方**：CI 不跑它，`quality_gate.py` 也不能递归自调
（自检里要跑 quality_gate，自调即死循环），此前只有一个测 stderr 编码的用例 import
了它的两个函数。于是 18 项自检里绝大部分从未被任何流水线执行过 —— 「防线没人跑」
和「没有防线」是同一个结果。

本用例把「CI 必须有一条 step 真的执行它」写成机器判定：下次重构把那条 step 删掉、
改名或注释掉，这里当场变红。
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SELFTEST = REPO / "scripts" / "_selftest_gate.py"
GATE = REPO / "scripts" / "quality_gate.py"
CI = REPO / ".github" / "workflows" / "ci-cd.yml"

#: 自检里不可静默丢失的语义面（每条都对应一次真实事故/评审结论）。
REQUIRED_CHECKS = (
    "_check_n_plus_one_semantics",   # N+1 判定不退化 + 白名单僵尸键
    "find_zombie_keys",              # 改名函数 / 越界行号 / 已删文件必须报
    "PYTHONIOENCODING",              # 子进程 stderr 按 utf-8 读回（否则中文断言恒红）
)


def _non_comment_lines(text: str) -> str:
    """去掉整行 YAML 注释：只在注释里提到脚本名不算「有调用方」。"""
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def test_selftest_gate_script_exists() -> None:
    assert SELFTEST.is_file(), f"跨门禁自检脚本不见了：{SELFTEST}"


def test_selftest_gate_is_invoked_by_ci() -> None:
    ci = _non_comment_lines(CI.read_text(encoding="utf-8"))
    assert "scripts/_selftest_gate.py" in ci, (
        "CI 里没有任何一条 step 执行 scripts/_selftest_gate.py —— "
        "它的 18 项自检就等于不存在（只有注释提到它不算）"
    )


def test_selftest_gate_is_not_self_recursive() -> None:
    """quality_gate 不得调用自检：自检内部要跑 quality_gate，自调即死循环。"""
    gate = GATE.read_text(encoding="utf-8")
    assert "_selftest_gate" not in gate, (
        "quality_gate.py 不得调用 _selftest_gate.py（自检内部会跑 quality_gate，会死循环）"
    )


def test_selftest_gate_still_covers_critical_semantics() -> None:
    src = SELFTEST.read_text(encoding="utf-8")
    missing = [name for name in REQUIRED_CHECKS if name not in src]
    assert missing == [], (
        f"自检丢失了这些语义面（别当清理死代码删掉，它们是防线本身）：{missing}"
    )
