"""A 止血改动的静态回归锁:停止范围(含 Redis)、受管集合、端口判据、环境变量写入。

无 GUI 测试基建,沿用本仓既有做法以文本断言锁定(见 test_server_manager_erp_web.py)。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

# 2026-09-28 包化:实现已拆到 server_manager/ 包,本文件按"整包拼接"取文本。
# ★ 修正(T4):此前假设"代码搬到别的模块后本文件无需改"——已实测证伪。凡用
#   ``TEXT.index(锚点)`` 切片的断言,在实现搬家后会命中同名的**瘦转发体**
#   (app.py 按 sorted(glob) 排在前面),断言虽仍绿但锁的是空壳。故凡锚点函数
#   已迁出的断言,改用 ``_func_src(模块, 函数名)`` 按 AST 精确定位目标模块内的
#   函数体,不依赖任何模块顺序/转发块摆放。非锚点切片断言一字未动。
PKG = Path(__file__).resolve().parent.parent / "server_manager"
TEXT = "\n".join(p.read_text(encoding="utf-8") for p in sorted(PKG.glob("*.py")))


def _func_src(rel_path: str, name: str) -> str:
    """按 AST 取指定模块内某函数/方法的源码段(含缩进),不依赖 TEXT.index 顺序。"""
    src = (PKG / rel_path).read_text(encoding="utf-8")
    lines = src.splitlines()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return "\n".join(lines[node.lineno - 1 : node.end_lineno])
    raise AssertionError(f"{rel_path} 内未找到 {name}")


# ── 受管服务全集 ───────────────────────────────────────────────────────────
def test_svc_all_constant_covers_five_services() -> None:
    """受管全集必须含两个 Redis 服务——否则「全部停止」名不副实(评审确认项)。"""
    m = re.search(r"^_SVC_ALL = \((.+)\)$", TEXT, re.M)
    assert m, "缺少 _SVC_ALL 常量"
    members = m.group(1)
    for name in ("_SVC_API", "_SVC_ARQ", "_SVC_WEB", "_SVC_REDIS_CACHE", "_SVC_REDIS_BROKER"):
        assert name in members, f"_SVC_ALL 缺 {name}"


def test_stop_paths_use_svc_all() -> None:
    """停止/重启/受管 PID 排除三条路径都必须按 _SVC_ALL 迭代(T4 起实现已迁 service_ops)。"""
    for fn in ("managed_service_pids", "stop_managed_services", "service_cmd_sync"):
        body = _func_src("service_ops.py", fn)
        assert "for name in _SVC_ALL" in body, f"{fn} 未按 _SVC_ALL 迭代"


def test_start_path_keeps_dedicated_redis_helpers() -> None:
    """启动流程不得改用 _SVC_ALL:Redis 由专属助手先起,复用会重复启动。"""
    body = TEXT[TEXT.index("def _start_services_flow") :][:1600]
    assert "for name in _SVC_ALL" not in body
    assert "_start_redis()" in body


def test_ensure_production_stopped_does_not_stop_redis() -> None:
    """切开发模式前的「停生产」不得停 Redis——开发模式同样依赖它(T4 起实现已迁 service_ops)。"""
    body = _func_src("service_ops.py", "ensure_production_stopped")
    assert "for name in _SVC_ALL" not in body


# ── 端口判据 ───────────────────────────────────────────────────────────────
def test_managed_pid_set_excluded_from_port_cleanup() -> None:
    """_release_ports 必须传受管 PID 排除集,否则「启动服务」会强杀在跑的生产进程。

    2026-09-30 起 exclude= 改为关键字传参并附带 managed_pids_fn 兜底（受管集合
    不可知时 fail-safe 放弃清理），断言随之更新。

    2026-10-26：原先用 `[TEXT.index(...)][:900]` 截断，docstring 一变长就把代码挤出
    窗口 → 断言假红。改为切到**方法结尾**（同缩进的下一个 def/class），只测试语义。
    """
    start = TEXT.index("def _release_ports")
    rest = TEXT[start + 1:]
    end = rest.find("\n    def ")
    body = rest if end == -1 else rest[:end]
    assert "exclude=managed" in body and "_managed_service_pids()" in body
    # 受管集合不可知时必须放弃清理而不是按空集照杀 —— fail-safe 闸门
    assert "managed_unknown" in body
    # 2026-10-26：杀完必须确认结果（'still_occupied'），不能拿「发过 taskkill」当成功
    assert "still_occupied" in body


def test_substring_port_killer_is_gone() -> None:
    """子串匹配端口的 _kill_port_process(':5002' 命中 ':50021')必须删除,只留精确版。"""
    assert "def _kill_port_process" not in TEXT
    assert "def _get_port_occupier" not in TEXT


def test_stop_redis_never_kills_by_port() -> None:
    """_stop_redis 不得再按端口盲杀——那会 taskkill 掉 NSSM 受管的 erp-redis。

    T3 已把实现迁入 redis_ops.py(改名 stop_redis),故按 AST 锁目标模块函数体。
    """
    body = _func_src("redis_ops.py", "stop_redis")
    assert "_kill_port_process" not in body


# ── 环境变量写入 ───────────────────────────────────────────────────────────
def test_env_extra_written_as_multiple_argv_elements() -> None:
    """AppEnvironmentExtra 必须逐元素传参:NSSM 只按第一个 '=' 切分单个元素,
    拼成一串会让 6 个变量里只剩 1 个(且值畸变),而界面仍报「已注册」。

    T4 起 _nssm_install/_apply_depends 已迁 service_ops(改名去下划线),故按 AST
    锁目标模块函数体;调用点 _install_services_flow 仍在 app,锚点不变。
    """
    body = _func_src("service_ops.py", "nssm_install")
    assert "AppEnvironmentExtra" in body
    # 值以列表传入、写入时按元素展开
    assert "isinstance(val, list)" in body, "未按列表值逐元素展开"
    assert "[nssm, 'set', name, key]" in body, "未见按 key 组装 argv 的写法"
    # 调用点须构造列表而非空格拼接的整串
    flow = TEXT[TEXT.index("def _install_services_flow") :][:900]
    assert "env_extra = [" in flow, "env_extra 应以列表构造"
    assert "' '.join" not in flow, "env_extra 不应再用空格拼成单串"
