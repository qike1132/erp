"""B 去重的静态回归锁:轮询/探活/解码/终止 四类原语各只留一份实现。

无 GUI 测试基建,沿用本仓做法以文本断言锁定。断言的是"机制唯一"而非具体写法,
故收敛内部实现时不需要改测试。
"""
from __future__ import annotations

import ast
from pathlib import Path

# 2026-09-28 包化:实现已拆到 server_manager/ 包,本文件按"整包拼接"取文本。
# ★ 修正(T3):此前假设"代码搬到别的模块后本文件无需改"——已实测证伪。凡用
#   ``TEXT.index(锚点)`` 切片的断言,在实现搬家后会命中同名的瘦转发体(或按
#   sorted(glob) 的字典序落到别的模块),切片指向错误位置。故涉模块的断言改用
#   ``_func_src(模块, 函数名)`` 按 AST 精确定位目标模块内的函数体,不依赖任何
#   模块顺序假设。
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



# ── b1 轮询原语 ────────────────────────────────────────────────────────────
def test_single_service_poll_primitive() -> None:
    """服务状态轮询只应有一处 deadline 循环(_wait_service),其余为调用方。

    其余 deadline 循环仅允许闸门的 wait_idle(语义不同,不合并)。
    """
    assert "def _wait_service(" in TEXT, "缺少统一的 _wait_service"
    n = TEXT.count("deadline = time.monotonic()")
    assert n <= 2, f"仍存在 {n} 处手写 deadline 轮询(应 ≤2:wait_idle + _wait_service)"


def test_wait_service_callers() -> None:
    # app 侧三个调用点(T4 前仍在 app)
    for fn in ("_wait_service_stopped", "_stop_managed_services", "_wait_service_running"):
        assert "_wait_service(" in _func_src("app.py", fn), f"{fn} 未复用 _wait_service"
    # redis 启停层已搬入 redis_ops(T3):按模块内语义锁复用注入的 wait_service
    assert "_wait_service(" in _func_src("redis_ops.py", "start_redis_via_service"), \
        "start_redis_via_service 未复用注入的 _wait_service"


def test_emergency_stop_poll_skips_checkpoint() -> None:
    """紧急停止的轮询必须不 checkpoint,否则 cancel 已置位时会半路抛出。"""
    body = TEXT[TEXT.index("def _stop_managed_services") :][:1600]
    assert "checkpoint=False" in body, "紧急停止轮询必须显式关闭 checkpoint"


# ── b2 Redis 探活 ─────────────────────────────────────────────────────────
def test_single_redis_ping_primitive() -> None:
    """RESP 探活唯一实现(T3 已迁 redis_ops):ping 内 3 次 sendall,is_* 复用它。"""
    ping_body = _func_src("redis_ops.py", "ping")
    # RESP 报文只出现在唯一实现里(3 次 sendall:首次 PING / AUTH / AUTH 后 PING)
    assert ping_body.count("sock.sendall") == 3, "RESP 报文应只在 ping 内(3 次 sendall)"
    assert TEXT.count("sock.sendall") == 3, "RESP 报文散落在 ping 之外"
    for fn in ("is_redis_running", "is_broker_running"):
        assert "self.ping(" in _func_src("redis_ops.py", fn), f"{fn} 未复用 ping"


# ── b3 解码器 ─────────────────────────────────────────────────────────────
def test_single_decoder_with_utf16_option() -> None:
    """字节流解码只应留一份实现,且必须带 UTF-16 分支(nssm 输出是 UTF-16LE)。"""
    assert TEXT.count("gb18030") <= 1, "候选编码列表出现多份 → 解码器未收敛"
    assert "def _decode_line" not in TEXT, "_decode_line 应已并入 _decode_output"
    assert "utf-16-le" in TEXT, "统一解码器丢掉了 UTF-16 分支"
    assert "strip=True" in TEXT, "统一解码器未提供逐行去尾的入口"


# ── b4 开发进程终止 ────────────────────────────────────────────────────────
def test_single_dev_terminate_primitive() -> None:
    assert "def _terminate_dev_processes(" in TEXT, "缺少统一的开发进程终止"
    n = TEXT.count("for proc, name in [(self._frontend_process, '前端'), (self._process, '后端')]")
    assert n <= 1, f"仍有 {n} 处复制的终止循环"


# ── b5/b6 Redis 状态解析与死采集键 ──────────────────────────────────────────
def test_redis_service_state_reuses_svc_state() -> None:
    body = _func_src("redis_ops.py", "redis_service_state")
    assert "_svc_state(" in body, "Redis 服务状态未复用注入的 _svc_state(拿不到三态语义)"


def test_dead_collect_keys_removed() -> None:
    """4 个只写不读的采集键(每 5 秒白跑 2 次 sc query)必须删除。"""
    for key in ("'arq_unknown'", "'redis_svc_state'", "'broker_svc_state'", "'status_file'"):
        assert key not in TEXT, f"未消费的采集键 {key} 仍在"


# ── 死代码 ────────────────────────────────────────────────────────────────
def test_debug_mode_subsystem_removed() -> None:
    """无 UI 入口、无调用者的调试模式子系统(用户确认删除)。"""
    for sym in ("def start_debug", "def stop_debug", "def restart_debug", "def _start_debug_flow"):
        assert sym not in TEXT, f"{sym} 仍在"
