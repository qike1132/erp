"""B 去重的静态回归锁:轮询/探活/解码/终止 四类原语各只留一份实现。

无 GUI 测试基建,沿用本仓做法以文本断言锁定。断言的是"机制唯一"而非具体写法,
故收敛内部实现时不需要改测试。
"""
from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "server_manager.py"
TEXT = SRC.read_text(encoding="utf-8")


# ── b1 轮询原语 ────────────────────────────────────────────────────────────
def test_single_service_poll_primitive() -> None:
    """服务状态轮询只应有一处 deadline 循环(_wait_service),其余为调用方。

    其余 deadline 循环仅允许闸门的 wait_idle(语义不同,不合并)。
    """
    assert "def _wait_service(" in TEXT, "缺少统一的 _wait_service"
    n = TEXT.count("deadline = time.monotonic()")
    assert n <= 2, f"仍存在 {n} 处手写 deadline 轮询(应 ≤2:wait_idle + _wait_service)"


def test_wait_service_callers() -> None:
    for fn in ("_start_redis_via_service", "_wait_service_stopped",
               "_stop_managed_services", "_wait_service_running"):
        body = TEXT[TEXT.index(f"def {fn}") :][:1500]
        assert "_wait_service(" in body, f"{fn} 未复用 _wait_service"


def test_emergency_stop_poll_skips_checkpoint() -> None:
    """紧急停止的轮询必须不 checkpoint,否则 cancel 已置位时会半路抛出。"""
    body = TEXT[TEXT.index("def _stop_managed_services") :][:1600]
    assert "checkpoint=False" in body, "紧急停止轮询必须显式关闭 checkpoint"


# ── b2 Redis 探活 ─────────────────────────────────────────────────────────
def test_single_redis_ping_primitive() -> None:
    assert "def _redis_ping(" in TEXT, "缺少统一的 _redis_ping"
    for fn in ("_is_redis_running", "_is_broker_running"):
        body = TEXT[TEXT.index(f"def {fn}") :][:600]
        assert "_redis_ping(" in body, f"{fn} 未复用 _redis_ping"
    # RESP 报文只应出现在一处
    assert TEXT.count("b'*1\\r\\n$4\\r\\nPING") <= 1 or TEXT.count("PING") <= 3


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
    body = TEXT[TEXT.index("def _redis_service_state") :][:700]
    assert "_svc_state(" in body, "Redis 服务状态未复用 _svc_state(拿不到三态语义)"


def test_dead_collect_keys_removed() -> None:
    """4 个只写不读的采集键(每 5 秒白跑 2 次 sc query)必须删除。"""
    for key in ("'arq_unknown'", "'redis_svc_state'", "'broker_svc_state'", "'status_file'"):
        assert key not in TEXT, f"未消费的采集键 {key} 仍在"


# ── 死代码 ────────────────────────────────────────────────────────────────
def test_debug_mode_subsystem_removed() -> None:
    """无 UI 入口、无调用者的调试模式子系统(用户确认删除)。"""
    for sym in ("def start_debug", "def stop_debug", "def restart_debug", "def _start_debug_flow"):
        assert sym not in TEXT, f"{sym} 仍在"
