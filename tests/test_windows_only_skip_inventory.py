"""1.7（2026-10-17 审计 TEST 区 P2）：Linux CI 上「恒 skip」的 Windows-only 用例必须可见、可判定。

问题不在这些用例本身（server_manager 的 NSSM 启停、PowerShell 迁移脚本、Windows Job
Object 语义在 Linux 上根本没有可执行的实现），而在于**没人知道它们没跑**：
CI 全绿看起来等于「全部覆盖」，实际这 20 条在 ubuntu runner 上一条都没执行，
相关代码（`server_manager/`、`scripts/migrate_erp_web.ps1`、`core.prod_runner` 的
Job Object 分支）的唯一验证发生在**生产机本地**。

本文件把三件事写成机器判定：
1. **清单冻结**：哪些用例在 Linux 上恒 skip，逐条登记。新增/删除必须显式改本文件
   （否则「静默多了一堆永远不跑的用例」和「删掉了验证」都发现不了）。
2. **skip 必须带 Windows 理由**：`skipif` 缺 `reason` 或理由不点明 Windows，一律红 ——
   裸 skip 在 CI 日志里只剩一个 `s`，看不出为什么。
3. **CI 步骤名必须标注**：跑主套件那一步的 `name:` 要写明这批用例在 Linux 恒 skip 且
   指向本文件，让人看流水线时就撞上这件事，而不是读文档才知道。

配套口径见 docs/agents/verification-and-review.md（§测试有效性）。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CI = REPO / ".github" / "workflows" / "ci-cd.yml"

#: 参与 pytest 的三棵测试树（与 pytest.ini 的 testpaths + prod_audit 自检一致）。
TREES = (
    REPO / "tests",
    REPO / "fastapi_app" / "tests",
    REPO / "scripts" / "prod_audit" / "tests",
)

#: 「平台条件」的判据：条件里必须真的读平台，否则不算 Windows-only。
PLATFORM_NEEDLES = ("sys.platform", "platform.system", "os.name")

#: 冻结清单：file -> 在非 Windows 上恒 skip 的用例（`Class::test` 形式表方法）。
#: 2026-11-19 实测冻结；与 pytest 收集结果一一对应（无参数化，见下面第三条判定）。
WINDOWS_ONLY_TESTS: dict[str, tuple[str, ...]] = {
    "tests/test_migrate_erp_web_dryrun.py": (
        "test_dryrun_order_stop_before_start_web_before_start_prod",
        "test_dryrun_prints_sequence",
    ),
    "tests/test_server_manager_start_services_flow.py": (
        "TestStartServicesFlow::test_flow_aborts_when_port_release_fails",
        "TestStartServicesFlow::test_flow_refuses_before_any_side_effect_on_branch_denial",
        "TestStartServicesFlow::test_flow_reports_incomplete_when_arq_broker_missing",
        "TestStartServicesFlow::test_flow_survives_redis_returning_false",
        "TestStartServicesFlow::test_start_redis_forwarding_exists",
        "TestStartServicesFlow::test_start_services_flow_reaches_redis_start",
    ),
    "tests/test_server_manager_stop_all_window.py": (
        "TestOpAbortedDuringStopAll::test_op_aborted_does_not_reset_mode_during_sweep",
        "TestOpAbortedDuringStopAll::test_op_aborted_resets_mode_when_not_stopping_all",
        "TestOpAbortedDuringStopAll::test_stop_all_done_resets_mode_after_sweep",
    ),
    "tests/test_server_manager_v533_stop.py": (
        "TestFindPortPidsExclude::test_exclude_managed_pid_skipped",
        "TestFindPortPidsExclude::test_no_exclude_returns_all",
        "TestFindPortPidsExclude::test_port_substring_not_matched",
    ),
    "tests/test_sm_workers_apply.py": (
        "test_restart_one_service_restarts_only_the_named_one",
    ),
    "fastapi_app/tests/test_prod_runner_job_object.py": (
        "test_job_close_kills_member_processes",
        "test_job_unavailable_is_non_fatal",
        "test_member_children_inherit_job_membership",
    ),
    "fastapi_app/tests/test_prod_runner_signal_handler.py": (
        "test_console_handler_callback_survives_gc",
        "test_installed_handler_can_still_invoke_shutdown",
    ),
}

#: CI 主套件步骤名必须带这句（改步骤名时同步改这里；两处都在判定面上，不算第二真相源）。
CI_LABEL = "恒 skip 的 Windows-only 用例"


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO)).replace("\\", "/")


def _is_platform_skip(node: ast.AST) -> bool:
    """节点（Call/Assign/装饰器）是否为「平台条件 skipif」。"""
    src = ast.unparse(node)
    if "skipif" not in src:
        return False
    return any(needle in src for needle in PLATFORM_NEEDLES)


def _decorator_names(node: ast.AST) -> list[str]:
    return [ast.unparse(dec) for dec in getattr(node, "decorator_list", [])]


def _collect_from_module(mod: ast.Module) -> list[str]:
    """按 4 种写法收集恒 skip 的用例：模块级 pytestmark / 模块级别名 / 类装饰器 / 函数装饰器。"""
    module_wide = False
    aliases: set[str] = set()
    for stmt in mod.body:
        if not isinstance(stmt, ast.Assign):
            continue
        names = {t.id for t in stmt.targets if isinstance(t, ast.Name)}
        if not _is_platform_skip(stmt.value):
            continue
        if "pytestmark" in names:
            module_wide = True
        aliases |= names - {"pytestmark"}

    def _skipped_on_platform(node: ast.AST) -> bool:
        if module_wide:
            return True
        return any(
            _is_platform_skip(dec) or ast.unparse(dec) in aliases
            for dec in getattr(node, "decorator_list", [])
        )

    hits: list[str] = []
    for node in ast.walk(mod):
        if isinstance(node, ast.ClassDef):
            class_skipped = _skipped_on_platform(node)
            for sub in node.body:
                if not isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if not sub.name.startswith("test_"):
                    continue
                if class_skipped or _skipped_on_platform(sub):
                    hits.append(f"{node.name}::{sub.name}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # 类方法已在上面按 `Class::method` 收集，这里只取模块级函数。
            if node.name.startswith("test_") and _skipped_on_platform(node):
                hits.append(node.name)
    return sorted(set(hits))


def _scan() -> dict[str, tuple[str, ...]]:
    found: dict[str, tuple[str, ...]] = {}
    for tree in TREES:
        for path in sorted(tree.rglob("test_*.py")):
            mod = ast.parse(path.read_text(encoding="utf-8"), str(path))
            hits = _collect_from_module(mod)
            if hits:
                found[_rel(path)] = tuple(hits)
    return found


def _platform_skip_nodes(mod: ast.Module) -> list[ast.AST]:
    """所有平台条件 skipif 节点（含装饰器与被赋值的 value），用于检查 reason。"""
    nodes: list[ast.AST] = []
    for node in ast.walk(mod):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nodes += [d for d in node.decorator_list if _is_platform_skip(d)]
        elif isinstance(node, ast.Assign) and _is_platform_skip(node.value):
            nodes.append(node.value)
    return nodes


def _ci_main_suite_step() -> tuple[str, str]:
    """返回（步骤名, run 块）——主套件步骤 = run 块里同时出现 `tests` 与 `fastapi_app/tests`。"""
    lines = CI.read_text(encoding="utf-8").splitlines()
    current_name = ""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("- name:"):
            current_name = stripped[len("- name:"):].strip()
            continue
        if stripped != "run: |":
            continue
        # 块内容缩进必须**深于** `run:` 行本身（步骤缩进随 job 层级变化，别写死 9 个空格）。
        run_indent = len(line) - len(line.lstrip())
        block: list[str] = []
        for follow in lines[i + 1:]:
            if follow.strip() and (len(follow) - len(follow.lstrip())) <= run_indent:
                break
            block.append(follow)
        body = "\n".join(block)
        if "fastapi_app/tests" in body and re.search(r"\btests\b", body):
            return current_name, body
    return "", ""


def test_frozen_inventory_matches_reality() -> None:
    """冻结清单必须与真实扫描结果一致（两边都查：静默新增 / 静默删除）。"""
    found = _scan()
    added = sorted(
        f"{path}::{name}" for path, names in found.items()
        for name in names if name not in WINDOWS_ONLY_TESTS.get(path, ())
    )
    removed = sorted(
        f"{path}::{name}" for path, names in WINDOWS_ONLY_TESTS.items()
        for name in names if name not in found.get(path, ())
    )
    assert added == [], (
        "这些用例新变成「Linux 上恒 skip」但没登记 —— 它们不会在 CI 里跑，"
        f"必须显式写进 WINDOWS_ONLY_TESTS 并想清楚谁来验证：{added}"
    )
    assert removed == [], (
        f"清单里的用例已不存在或不再恒 skip（删除验证要显式登记，别让清单变成僵尸）：{removed}"
    )


def test_every_platform_skip_declares_a_windows_reason() -> None:
    """平台条件 skip 必须带 reason，且理由点明 Windows：CI 日志里只看到 `s` 等于没解释。"""
    offenders: list[str] = []
    for tree in TREES:
        for path in sorted(tree.rglob("test_*.py")):
            mod = ast.parse(path.read_text(encoding="utf-8"), str(path))
            for node in _platform_skip_nodes(mod):
                call = node if isinstance(node, ast.Call) else None
                reason_kw = None
                if call is not None:
                    reason_kw = next((kw.value for kw in call.keywords if kw.arg == "reason"), None)
                if reason_kw is None:
                    offenders.append(f"{_rel(path)}:{node.lineno} 缺 reason=")
                    continue
                text = ast.unparse(reason_kw)
                if "windows" not in text.lower() and "Windows" not in text:
                    offenders.append(f"{_rel(path)}:{node.lineno} reason 未点明 Windows：{text}")
    assert offenders == [], f"平台 skip 必须写清「为什么只在 Windows 能跑」：{offenders}"


def test_windows_only_tests_are_not_parametrized() -> None:
    """清单按「用例函数」计数，参数量会让真实 skip 数翻倍 —— 有 parameterize 就不许进清单。"""
    offenders: list[str] = []
    for path, names in WINDOWS_ONLY_TESTS.items():
        mod = ast.parse((REPO / path).read_text(encoding="utf-8"), path)
        for node in ast.walk(mod):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            qual = node.name
            short = [n for n in names if n == qual or n.endswith(f"::{qual}")]
            if not short:
                continue
            if any("parametrize" in dec for dec in _decorator_names(node)):
                offenders.append(f"{path}::{qual}")
    assert offenders == [], (
        f"清单里的用例被参数化了，实际 skip 数量已不等于清单条数，请改用逐条登记：{offenders}"
    )


def test_ci_step_name_flags_windows_only_skips() -> None:
    """CI 主套件步骤名必须标注这批恒 skip 并指向本文件：看流水线就知道哪里没覆盖。"""
    name, body = _ci_main_suite_step()
    assert body, "没在 ci-cd.yml 里找到跑主套件（tests + fastapi_app/tests）的步骤"
    assert CI_LABEL in name, (
        f"CI 主套件步骤名缺少标注「{CI_LABEL}」：当前 name = {name!r}。"
        "流水线全绿会被误读成「全部覆盖」，而这 20 条在 Linux 上根本没跑。"
    )
    assert "test_windows_only_skip_inventory" in name, (
        f"CI 步骤名应指向清单文件，方便一眼找到哪些用例没跑：当前 name = {name!r}"
    )
