# tests/test_gates_cover_repo_root.py
"""T6 回归锁:规模门禁与函数长度门禁的扫描范围必须含**仓库根顶层** .py。

背景:两个门禁的扫描目录此前只有 ``fastapi_app`` / ``tests`` / ``utils`` /
``scripts``,仓库根被排除 —— 拆包前那个 3082 行的 ``server_manager.py`` 恰好
躺在仓库根,于是这个全仓最大的文件从未进过门禁(本计划 T6 收尾项)。

只读脚本源码文本,不 import 任何运行时依赖(``check_function_length`` import 时
会改写 ``sys.stdout``,进程内 import 会打坏 pytest 捕获),CI 可跑。
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_file_size_gate_scans_repo_root() -> None:
    """规模门禁须把仓库根顶层 ``*.py`` 纳入全量扫描范围。

    注意不能只断言 ``glob("*.py")`` —— 既有 ``rglob("*.py")`` 就含该子串,
    那样的断言恒真(空转锁)。必须锚定**仓库根**上的 glob。
    """
    text = (ROOT / "scripts" / "file_size_gate.py").read_text(encoding="utf-8")
    assert 'PROJECT_ROOT.glob("*.py")' in text, "file_size_gate 未纳入仓库根顶层 .py"


def test_function_length_gate_scans_repo_root() -> None:
    """函数长度门禁须把仓库根并入默认扫描目录,且根目录只取**顶层** ``*.py``。"""
    text = (ROOT / "scripts" / "check_function_length.py").read_text(encoding="utf-8")
    assert "PROJECT_ROOT" in text and "DEFAULT_SCAN_DIRS" in text
    # 根目录若用 rglob 会递归进 frontend-vite/node_modules,必须限定顶层。
    assert 'd.glob("*.py")' in text, "根目录扫描未限定为顶层 *.py"


# ---------------------------------------------------------------------------
# CI 待补(T6 硬约束):``.github/workflows/ci-cd.yml`` 正被并发会话持有(未提交),
# ``git add <该文件>`` 会把他人的改动一起提交(本计划已发生过一次准事故)。
# 故本任务**跳过 CI 那一行** —— 该文件当前仍是 ``python scripts/file_size_gate.py``
# (git-diff 模式在 CI 干净检出里恒为空,等于空转),待控制器补 ``--all`` 后,
# 删除下面的 skip 让本条真正生效。见 task-6-report.md『CI 待补』条目。
# ---------------------------------------------------------------------------
@pytest.mark.skip(
    reason="DEFERRED(T6): ci-cd.yml 由并发会话持有,--all 一行待控制器补;补后删本 skip。"
)
def test_ci_uses_all_mode() -> None:
    text = (ROOT / ".github" / "workflows" / "ci-cd.yml").read_text(encoding="utf-8")
    assert "file_size_gate.py --all" in text, "CI 仍在用会空转的 git-diff 模式"
