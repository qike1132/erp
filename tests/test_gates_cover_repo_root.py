# tests/test_gates_cover_repo_root.py
"""T6 回归锁:规模门禁与函数长度门禁必须"看得见"仓库根与桌面壳包。

背景:两个门禁的扫描目录此前只有 ``fastapi_app`` / ``tests`` / ``utils`` /
``scripts``,仓库根与 ``server_manager/`` 包都被排除 —— 拆包前那个 3082 行的
``server_manager.py`` 恰在仓库根、拆包后它的主体又落进 ``server_manager/`` 包,
于是**全仓最大的 .py 两轮都逃过门禁**(本计划 T6 收尾项)。

断言策略:
  - 源码字面量锁(便宜、直白) + **行为锁**(跑真门禁,确认它真的看见了/报得出);
  - 不 import 被测脚本到本进程:``file_size_gate`` / ``check_function_length``
    在 import 期会 ``sys.stdout = io.TextIOWrapper(sys.stdout.buffer, ...)``,
    会把 pytest 的捕获流包掉(可能连带关闭其 buffer)。故一律走子进程。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_PY = ROOT / "server_manager" / "app.py"
PYPROJECT = ROOT / "pyproject.toml"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    """在仓库根跑子进程,统一 UTF-8 解码(中文 Windows 默认 cp936 会炸)。"""
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
    )


def _max_file_size() -> int:
    """阈值唯一来源:``pyproject.toml [tool.code-quality] max_file_size``。"""
    import tomllib

    with PYPROJECT.open("rb") as fh:
        data = tomllib.load(fh)
    return int(((data.get("tool") or {}).get("code-quality") or {})["max_file_size"])


# ---------------------------------------------------------------------------
# 规模门禁
# ---------------------------------------------------------------------------


def test_file_size_gate_scans_repo_root() -> None:
    """规模门禁的扫描范围须含仓库根顶层,且锚定**仓库根**的 glob。

    注意不能只断言 ``glob("*.py")`` —— 既有 ``rglob("*.py")`` 就含该子串,
    那样的断言恒真(空转锁)。必须锚定 ``PROJECT_ROOT.glob("*.py")``。
    """
    text = (ROOT / "scripts" / "file_size_gate.py").read_text(encoding="utf-8")
    assert 'PROJECT_ROOT.glob("*.py")' in text, "file_size_gate 未纳入仓库根顶层 .py"
    assert '"server_manager"' in text, "file_size_gate 未纳入桌面壳包(全仓最大 .py 的所在)"


def test_file_size_gate_scan_set_includes_root_and_package() -> None:
    """行为锁:门禁的**扫描集合**真的含仓库根薄壳与 ``server_manager/app.py``。

    只锁源码字面量挡不住"SCAN_DIRS 写了但拼接/过滤把包滤掉"这类改动,故实跑
    ``_all_py_files()``。本锁**永久成立**(不依赖行数),D 步把 app.py 拆小后亦不失效。
    """
    code = (
        "import json, sys; sys.path.insert(0, '.');"
        "from scripts.file_size_gate import _all_py_files;"
        "print(json.dumps([p.as_posix() for p in _all_py_files()]))"
    )
    proc = _run(["-c", code])
    assert proc.returncode == 0, f"_all_py_files() 调用失败:\n{proc.stderr}"
    scanned = set(json.loads(proc.stdout))
    assert any(p.endswith("server_manager/app.py") for p in scanned), (
        "规模门禁未纳入 server_manager 包 —— 全仓最大的 .py 仍然逃逸"
    )
    assert any(p.endswith("/server_manager.py") for p in scanned), (
        "规模门禁未纳入仓库根顶层 .py"
    )


def test_file_size_gate_reports_over_limit_package_file() -> None:
    """行为锁:门禁要**报得出** ``server_manager/app.py`` 这条超限,而不只是看得见。

    ⚠ 本条锁的是 2026-09-28 的**已知违规**(app.py > 阈值)。控制器裁定:如实报出、
    不放宽阈值,另开一步把它消掉。**D 步把 app.py 拆到 ≤ 阈值后**,本条的
    ``line_count > max_file_size`` 会先红 —— 届时删除本条,把"包已纳入扫描"的
    永久锁留给 ``test_file_size_gate_scan_set_includes_root_and_package``。
    """
    limit = _max_file_size()
    line_count = sum(1 for _ in APP_PY.open(encoding="utf-8", errors="replace"))
    assert line_count > limit, (
        f"server_manager/app.py 已降至 {line_count} 行(≤ 阈值 {limit}):"
        "已知违规已消除,请删除本测试"
    )

    proc = _run(["scripts/file_size_gate.py", "--all"])
    assert proc.returncode == 0, "无 --fail 的 --all 不应失败"
    expected = f"server_manager{os.sep}app.py: {line_count} 行"
    assert expected in proc.stdout, (
        f"--all 未报出 {expected!r}:\n{proc.stdout}\n{proc.stderr}"
    )


# ---------------------------------------------------------------------------
# 函数长度门禁
# ---------------------------------------------------------------------------


def test_function_length_gate_scans_repo_root() -> None:
    """函数长度门禁须把仓库根并入默认扫描目录,且根目录只取**顶层** ``*.py``。

    ⚠ ``server_manager`` 包**刻意不**并入默认扫描目录:app.py 的
    ``_apply_hosting_data() = 155 行`` 会让 quality_gate(pre-commit 与 CI 都跑)
    立刻变红;函数级拆分属 D 的范畴。(故此处的"不包含"是被裁定的,不是遗漏。)
    """
    text = (ROOT / "scripts" / "check_function_length.py").read_text(encoding="utf-8")
    assert "PROJECT_ROOT" in text and "DEFAULT_SCAN_DIRS" in text
    # 根目录若用 rglob 会递归进 frontend-vite/node_modules,必须限定顶层。
    assert 'd.glob("*.py")' in text, "根目录扫描未限定为顶层 *.py"
    assert "server_manager" not in text, (
        "server_manager 不应进 DEFAULT_SCAN_DIRS(app.py 的 155 行函数会让 quality_gate 变红)"
    )


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
