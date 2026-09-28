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

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_PY = ROOT / "server_manager" / "app.py"
PYPROJECT = ROOT / "pyproject.toml"


def _assigned_src(src: str, name: str) -> str:
    """取模块源码中名为 ``name`` 的**赋值语句**源码段(按 AST,支持多行定义)。

    用于把断言锚定到某条赋值本身,而非整文件文本 —— 见 #11:整文件文本锁会被
    无关的注释/字符串里的同名字串误伤。
    """
    lines = src.splitlines()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    return "\n".join(lines[node.lineno - 1 : node.end_lineno])
    raise AssertionError(f"未找到赋值语句 {name}")


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


def test_file_size_gate_package_file_within_limit() -> None:
    """回归锁:``server_manager/app.py`` 必须守在规模阈值以内,且门禁不再报它超限。

    ★ 本条的来历(T7 改写):原文是 ``test_file_size_gate_reports_over_limit_package_file``,
    断言的是 2026-09-28 的**已知违规**(app.py 1672 行 > 阈值 1600) —— 控制器裁定
    「如实报出、不放宽阈值,另开一步消掉」,故该锁只在违规存续期内成立。

    T7 把 hosting 视图层抽到 ``server_manager/hosting_view.py``(HostingViewMixin) 后
    app.py 降到阈值以内,原锁按其自身 docstring 的提示**改写为永久反向锁**:app.py 一旦
    再涨回阈值以上,或门禁又把它漏报出来,本条即红。「包已纳入扫描」这件永久的事由
    ``test_file_size_gate_scan_set_includes_root_and_package`` 单独锁住,与本条解耦。
    """
    limit = _max_file_size()
    line_count = sum(1 for _ in APP_PY.open(encoding="utf-8", errors="replace"))
    assert line_count <= limit, (
        f"server_manager/app.py 已涨到 {line_count} 行(> 阈值 {limit}):"
        "规模门禁会判红,请再抽一层出去"
    )

    proc = _run(["scripts/file_size_gate.py", "--all"])
    assert proc.returncode == 0, "无 --fail 的 --all 不应失败"
    assert f"server_manager{os.sep}app.py" not in proc.stdout, (
        f"--all 仍报出 server_manager{os.sep}app.py 超限:\n{proc.stdout}\n{proc.stderr}"
    )


# ---------------------------------------------------------------------------
# 函数长度门禁
# ---------------------------------------------------------------------------


def test_function_length_gate_scans_repo_root() -> None:
    """函数长度门禁须把仓库根并入默认扫描目录,且根目录只取**顶层** ``*.py``。

    ⚠ ``server_manager`` 包**刻意不**并入默认扫描目录:包内
    ``_apply_hosting_data() = 192 行``(T7 起位于 ``server_manager/hosting_view.py``)
    会让 quality_gate(pre-commit 与 CI 都跑)立刻变红;函数级拆分属 D 的范畴。
    (故此处的"不包含"是被裁定的,不是遗漏。)
    """
    text = (ROOT / "scripts" / "check_function_length.py").read_text(encoding="utf-8")
    assert "PROJECT_ROOT" in text and "DEFAULT_SCAN_DIRS" in text
    # 根目录若用 rglob 会递归进 frontend-vite/node_modules,必须限定顶层。
    assert 'd.glob("*.py")' in text, "根目录扫描未限定为顶层 *.py"
    # ★ 修正(#11):此前对**整文件**断言 ``"server_manager" not in text`` —— 将来任何
    #   注释/字符串里出现该串都会误红。改为只锚定 ``DEFAULT_SCAN_DIRS`` 的赋值段。
    scan_dirs_src = _assigned_src(text, "DEFAULT_SCAN_DIRS")
    assert "server_manager" not in scan_dirs_src, (
        "server_manager 不应进 DEFAULT_SCAN_DIRS(包内 192 行函数会让 quality_gate 变红)"
    )


# ---------------------------------------------------------------------------
# CI：规模门禁须对比 **PR 基线**取变更文件。
# 历史：T6 时 ci-cd.yml 由并发会话持有(未提交),本任务跳过该行;控制器于本波
# 采「--base origin/<base_ref>」对比基线(而非 --all —— 后者会把存量
# tests/test_outsource.py 判红,违背脚本"存量超限不阻断"的设计原则)。
# ---------------------------------------------------------------------------
def test_ci_uses_baseline_diff_mode() -> None:
    """CI 的规模门禁在 PR 事件上必须对比基线;push 回落的 ``--all`` **不得**带 ``--fail``。

    历史:干净检出里 git-diff(工作树 vs HEAD) 恒空 ⇒ 空转。改对比 PR 基线后,
    仓库根与 ``server_manager/`` 随变更集进入扫描范围(T6 的目标)。push 事件没有
    ``base_ref``,传 ``--base`` 只会得到解析不了的 ref,故改走 ``--all`` 全量报告;
    带 ``--fail`` 会把**存量** ``tests/test_outsource.py`` 判红、违背脚本
    「存量超限不阻断」的设计原则。
    """
    text = (ROOT / ".github" / "workflows" / "ci-cd.yml").read_text(encoding="utf-8")
    assert 'file_size_gate.py --base "origin/${{ github.base_ref }}"' in text, (
        "CI 文件规模门禁未对比 PR 基线(干净检出里会空转)"
    )
    assert "file_size_gate.py --all --fail" not in text, (
        "CI 的 --all 不得带 --fail(会把存量违规判红,违背脚本设计原则)"
    )


def test_file_size_gate_fails_loudly_on_unresolvable_base() -> None:
    """基线 ref 解析不了时必须**失败**(退出码非 0),不得静默跳过。

    I-1「CI 门禁半交付」的核心防线:此前「ref 解析不了」与「变更集为空」都落到
    「无扫描文件…跳过」+ 退出码 0 ⇒ CI 少了 ``fetch-depth: 0``、基线分支名不符、
    分支改名,都会让门禁悄悄退化成空转却报绿。本测试**真跑一次子进程**断言退出码,
    不是文本锁 —— 若把脚本里的响亮失败改回跳过,它必红。
    """
    proc = _run(["scripts/file_size_gate.py", "--base", "origin/no-such-ref-xyz"])
    assert proc.returncode != 0, (
        f"基线 ref 解析不了却退出 0(门禁空转):\n{proc.stdout}\n{proc.stderr}"
    )
    assert "无法解析" in proc.stderr, f"未给出明确错误信息:\n{proc.stderr}"


# ---------------------------------------------------------------------------
# server_manager 包内未使用导入(F401)的防漂移锁
# ---------------------------------------------------------------------------
def test_server_manager_package_has_no_unused_imports() -> None:
    """``server_manager/`` 包内 ruff F401 计数必须为 0。

    该目录**不在** CI 的 ruff 扫描范围(CI 只扫 ``fastapi_app tests
    fastapi_app/tests utils``)—— 本测试是唯一兜底,直接防住"每步从 app.py 摘掉
    某个 import 的最后一个使用者、却无人清理该 import"这一类漂移(包化过程中
    已实测发生:8 个死导入)。走子进程调用,避免 ruff 的 stdout 包装影响 pytest。
    """
    proc = _run(["-m", "ruff", "check", "server_manager/",
                 "--select", "F401", "--output-format", "concise"])
    assert proc.returncode == 0 and "F401" not in proc.stdout, (
        f"server_manager/ 存在未使用导入(F401):\n{proc.stdout}\n{proc.stderr}"
    )
