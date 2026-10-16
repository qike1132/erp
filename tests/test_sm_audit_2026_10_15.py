"""server_manager 2026-10-15 审计修复回归锁（纯 AST/文本，无 Tk，CI 可跑）。

锁定本次修复的四条核心契约：
1. 退出路径同步终止前后端 + 直接拉起的 Redis（消灭进程孤儿与守护线程竞态）；
2. 开发卡「停止」按钮接线（stop_cmd 不再悬空、stop_dual_dev UI 可达）；
3. wait_service_stopped 在 nssm 缺失时回退 sc stop（不再把 None 塞进 argv）;
4. 死转发已删（全仓无调用点才许删，锁住不回潮）。

运行: python -m pytest tests/test_sm_audit_2026_10_15.py -q
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "server_manager" / "app.py"
SVC_OPS = ROOT / "server_manager" / "service_ops.py"
DM = ROOT / "server_manager" / "dev_mode.py"
HOSTING_VIEW = ROOT / "server_manager" / "hosting_view.py"
LOG_VIEW = ROOT / "server_manager" / "log_view.py"

sys.path.insert(0, str(ROOT))


def _func_src(module: Path, name: str) -> str:
    """按 AST 取模块内某函数源码段（含缩进），不依赖文本顺序。"""
    src = module.read_text(encoding="utf-8")
    lines = src.splitlines()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return "\n".join(lines[node.lineno - 1 : node.end_lineno])
    raise AssertionError(f"{module.name} 内未找到 {name}")


# ── 1. 退出路径 ────────────────────────────────────────────────────────────

def _code_lines(src: str) -> list[str]:
    """去掉注释行与 docstring 后的纯代码行（防止断言误伤修复说明里的旧词）。"""
    out, in_doc = [], False
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith(('"""', "'''")):
            if not (in_doc and len(stripped) > 3):
                in_doc = not in_doc
                continue
            continue
        if in_doc or stripped.startswith('#'):
            continue
        out.append(line)
    return out


def test_do_quit_terminates_dev_processes_synchronously():
    """退出必须同步杀前后端 + 直接拉起的 Redis，不经闸门、不依赖守护线程。"""
    body = _func_src(APP, "_do_quit")
    assert "_terminate_dev_processes(" in body, "退出未用统一的开发进程终止原语"
    assert "_stop_redis()" in body, "退出未收掉直接拉起的 Redis（开发场景会泄漏 6379）"
    for forbidden in ("gate.start", "threading.Thread"):
        assert all(forbidden not in ln for ln in _code_lines(body)), \
            f"退出路径不得再经 {forbidden}（守护线程竞态）"


def test_stop_process_flow_removed():
    """旧的 _stop_process_flow 只杀后端且逐子冗余 kill，应随修复整体删除。"""
    src = APP.read_text(encoding="utf-8")
    assert "def _stop_process_flow" not in src, "已废弃的 _stop_process_flow 不应存在"
    assert "def _stop_process(" not in src, "已废弃的 _stop_process 不应存在"


def test_quit_still_stops_tailer():
    """既有契约（test_server_manager_log_ops 同款）：退出仍收掉回灌线程。"""
    assert "prod_logs.stop()" in _func_src(APP, "_do_quit")


# ── 2. 开发卡停止按钮 ──────────────────────────────────────────────────────

def test_stop_button_wired_and_params_not_dangling():
    """stop_cmd 必须渲染成真实按钮；_build_server_card 不再收悬空的 script_label。"""
    body = _func_src(APP, "_build_server_card")
    assert "command=stop_cmd" in body, "stop_cmd 未接线 —— stop_dual_dev 仍是 UI 不可达死方法"
    assert "script_label" not in body, "script_label 悬空参数未删"
    assert "state='disabled'" in body, "停止按钮初始应置灰（仅运行中可用）"


def test_stop_button_state_managed_by_update_card_ui():
    """_update_card_ui 必须接管 stop 按钮状态（只在运行中可用）。"""
    body = _func_src(APP, "_update_card_ui")
    assert "_stop_btn" in body, "_update_card_ui 未管理停止按钮状态"


def test_dev_card_button_row_no_dangling_args():
    """调用点与新签名一致（少传 script_label 位置参数）。"""
    src = APP.read_text(encoding="utf-8")
    call = "_build_server_card(content, 0, 0, '开发模式', 'FastAPI"
    assert call in src
    assert "self.stop_dual_dev" in src, "stop_dual_dev 不再被传入卡片 → 重新变死方法"


# ── 3. wait_service_stopped 的 sc 回退 ────────────────────────────────────

def test_wait_service_stopped_falls_back_to_sc():
    """nssm 缺失时必须回退 sc stop，不得把 None 塞进 argv（命令根本没发出）。"""
    body = _func_src(SVC_OPS, "wait_service_stopped")
    assert "'sc', 'stop'" in body, "缺 nssm 的 sc stop 回退"
    assert "self.find_nssm()" in body


def test_wait_service_stopped_sc_fallback_actually_issues_stop():
    """行为级验证：nssm=None 时确实发出 ['sc','stop',name] 且不因 None argv 失败。"""
    from server_manager.service_ops import ServiceOps

    ops = object.__new__(ServiceOps)
    ops._msg_queue = type("Q", (), {"put": lambda self, m: None})()
    ops._gate = None
    ops.find_nssm = lambda: None
    calls = []

    def fake_run_capture(args, timeout=20):
        calls.append(list(args))
        return 0, ""

    ops.run_capture = fake_run_capture
    ops.wait_service = lambda name, target, timeout, **kw: "1 STOPPED"
    assert ops.wait_service_stopped("erp-prod") is True
    assert ["sc", "stop", "erp-prod"] in calls, f"实际发出的命令: {calls}"


# ── 4. 死转发不回潮 ────────────────────────────────────────────────────────

DEAD_FORWARDERS = (
    "_get_env_value", "_redis_ping", "_redis_service_state",
    "_start_redis_via_service", "_start_redis_process",
    "_find_loose_prod_runner_pids", "_find_project_residual_pids",
    "_collect_process_tree",
)


def test_dead_forwarders_stay_removed():
    """2026-10-15 审计删除的 8 个零引用转发不得回潮（注释所称静态断言实测不存在）。"""
    src = APP.read_text(encoding="utf-8")
    for sym in DEAD_FORWARDERS:
        assert f"def {sym}" not in src, f"死转发 {sym} 回潮"


# ── 5. read_frontend_stdout 收尾对齐 ───────────────────────────────────────

def test_frontend_stdout_closes_stream():
    """前端 stdout 读取退出后必须关流（对齐 read_stdout 的 try/finally 契约）。"""
    body = _func_src(DM, "read_frontend_stdout")
    assert "finally:" in body, "缺 finally 收尾"
    assert "stdout.close()" in body, "未关闭管道句柄（悬到 GC）"


# ── 6. Worker 数主线程读取限时 ─────────────────────────────────────────────

def test_apply_workers_reads_with_short_timeout():
    """_apply_workers 的现状读取必须走短超时通道（默认 20s 会冻主线程）。"""
    body = _func_src(APP, "_apply_workers")
    assert "_read_workers_current" in body, "未改走限时读取助手"
    helper = _func_src(APP, "_read_workers_current")
    assert "read_timeout=3" in helper, "限时读取未设 3s 上限"
    # 限时失败(None)不得阻断变更：写侧 set_env_extra_key 自带回读校验兜底
    assert "current == target" in body  # None ≠ target，自然放行


def test_configured_workers_documented_main_thread_hazard():
    """首帧路径的 _configured_workers 已带超时说明（防止有人改回 20s 默认）。"""
    body = _func_src(APP, "_configured_workers")
    assert "3s" in body or "timeout" in body.lower(), "主线程阻塞隐患说明未随修复落档"


# ── 7. 装饰动画裁剪 ───────────────────────────────────────────────────────

def test_intro_animations_not_in_startup_sequence():
    """启动序列不得再挂 fade-in/卡片脉冲（低配机首帧拖累）。"""
    init = _func_src(APP, "__init__")
    for gone in ("_fade_in()", "_animate_cards_intro()"):
        assert gone not in init, f"{gone} 回潮到启动序列"


def test_env_check_dialog_not_delayed():
    """环境检查告警不再 after(500) 延迟（与已移除的首帧动画叠加没意义）。"""
    body = _func_src(APP, "_run_env_checks")
    assert all("after(500" not in ln for ln in _code_lines(body))
    assert "messagebox.showwarning" in body


# ── 8. 2026-10-16 结构评审修复（H1/H2/M1~M4/L1~L3）─────────────────────────

def test_dev_health_checks_bypass_proxy():
    """开发模式健康检查必须用 _HTTP_DIRECT 直连 opener（裸 urlopen 吃系统代理 → 间歇假失败）。

    ★ 且必须用 ``.open``：``OpenerDirector`` 没有 ``urlopen`` 方法（2026-10-16
    事故：写 .urlopen 每次必抛 AttributeError，被外层 except 吞掉 → 探测永远
    失败 → 杀掉已 startup complete 的健康后端）。
    """
    text = DM.read_text(encoding="utf-8")
    assert "_HTTP_DIRECT.open(" in text, "开发模式探测未绕开系统代理（H1）"
    body_start = _func_src(DM, "start_dual_thread")
    assert body_start.count("_HTTP_DIRECT.open(") == 2, "前后端两处探测都要走直连 opener"
    for ln in _code_lines(body_start):
        assert "_HTTP_DIRECT.urlopen" not in ln, ".urlopen 每次必抛 AttributeError（OpenerDirector 无此方法）"


def test_do_quit_cancels_inflight_action():
    """退出必须先取消在飞行动作并等它退出（否则刚 Popen 的进程照样孤儿，H2）。"""
    body = _func_src(APP, "_do_quit")
    assert "self._gate.cancel(" in body, "退出未取消在飞行动作"
    assert "wait_idle(" in body, "退出未等待在飞行动作退出"


def test_stop_all_locks_buttons_during_sweep():
    """紧急停止清扫窗口：按钮必须置灰、mode=stopping、_stopping_all 标志（M1/L4）。"""
    body = _func_src(APP, "stop_all")
    assert "_stopping_all = True" in body, "未置「全停中」标志（M3 联动）"
    assert "_set_actions_enabled(False)" in body, "清扫期间未置灰操作按钮（M1）"
    assert "self._mode = 'stopping'" in body, "未置 stopping 过渡态（L4）"
    # 完成消息必须复位标志并放开按钮（含异常路径；两处 put = 成功/异常两条路径）
    worker = _func_src(APP, "stop_all")
    assert worker.count("'stop_all_done'") == 2, "成功/异常两条路径都要发 stop_all_done"
    dispatch = _func_src(APP, "_process_pending_messages")
    assert "'stop_all_done'" in dispatch and "_stopping_all = False" in dispatch


def test_hosting_apply_drops_results_during_stop_all():
    """全停窗口内滞留的采集结果不得翻改 _prod_running（M3）。"""
    body = _func_src(HOSTING_VIEW, "_apply_hosting_data")
    assert "_stopping_all" in body, "渲染层未判「全停中」标志"


def test_web_svc_state_collected_off_main_thread():
    """erp-web 服务状态必须在采集阶段读，渲染阶段 sc query 冻主线程（M2）。"""
    collect = _func_src(HOSTING_VIEW, "_collect_hosting_data")
    assert "web_svc_state" in collect, "web 状态未在采集阶段读取"
    render = _func_src(HOSTING_VIEW, "_apply_running_status")
    assert "self._svc_state(" not in render, "渲染阶段仍在主线程跑 sc query"
    assert "web_svc_state" in render


def test_log_message_no_cross_thread_tk():
    """log_message 从 worker 线程被调：flush 必须经消息队列回主线程，不得 after_idle（M4）。"""
    body = _func_src(LOG_VIEW, "log_message")
    assert all("after_idle" not in ln for ln in _code_lines(body)), "跨线程 after_idle 是间歇崩溃来源"
    assert "log_flush" in body, "未改走队列投递"
    dispatch = _func_src(APP, "_process_pending_messages")
    assert "'log_flush'" in dispatch and "_do_flush()" in dispatch, "主线程未派发 log_flush"


def test_find_redis_forwarder_removed():
    """L1：_find_redis 死转发不得回潮（2026-10-16 结构评审补删）。"""
    src = APP.read_text(encoding="utf-8")
    assert "def _find_redis" not in src


def test_log_io_helpers_moved_to_log_ops():
    """L2：_log_size/_read_log_lines 应收编 log_ops，app 不再有纯文件 IO 方法。"""
    src = APP.read_text(encoding="utf-8")
    assert "def _log_size" not in src and "def _read_log_lines" not in src
    ops_text = (ROOT / "server_manager" / "log_ops.py").read_text(encoding="utf-8")
    assert "def log_file_size" in ops_text and "def read_log_tail_lines" in ops_text
    assert "log_ops.log_file_size" in src and "log_ops.read_log_tail_lines" in src


def test_decode_output_is_module_level():
    """L3：decode_output 应为模块级纯函数；类内保留转发、log_ops 不再 import ServiceOps。"""
    ops_text = (ROOT / "server_manager" / "log_ops.py").read_text(encoding="utf-8")
    assert "from server_manager.service_ops import decode_output" in ops_text
    assert "import ServiceOps" not in ops_text, "log_ops 不应为解码器依赖整个服务层"
    src = SVC_OPS.read_text(encoding="utf-8")
    assert "def decode_output(raw" in src, "模块级实现缺失"
    # run_capture 与既有调用点仍走同一实现（不产生第二真相源）
    assert "return decode_output(raw, strip=strip)" in src


def test_read_log_tail_lines_behavior():
    """行为级：read_log_tail_lines 只回灌 offset 之后的新增尾部（轮转重开按全新文件）。"""
    import tempfile

    from server_manager.log_ops import read_log_tail_lines

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "a.log"
        p.write_bytes(b"old line\r\n" * 10)
        offset = p.stat().st_size
        # 追加新内容 → 只回灌新增尾部
        with open(p, "ab") as f:
            f.write(b"new1\r\nnew2\r\nnew3\r\n")
        assert read_log_tail_lines(p, start_offset=offset, lines=2) == ["new2", "new3"]
        # 文件被轮转重开（size < offset）→ 按全新文件读尾部
        p.write_bytes(b"fresh\r\n")
        assert read_log_tail_lines(p, start_offset=offset, lines=5) == ["fresh"]
        # 不存在的文件 → 空列表不抛错
        assert read_log_tail_lines(Path(td) / "nope.log") == []


def test_decode_output_behavior_preserved():
    """行为级：提为模块级后解码行为逐字不变（UTF-16 BOM / GBK / replace 回退）。"""
    from server_manager.service_ops import decode_output

    assert decode_output("你好\r\n".encode("gbk"), strip=True) == "你好"
    assert decode_output("ok\r\n".encode("utf-16"), strip=True) == "ok"
    # NUL 密度启发（UTF-16LE 无 BOM）
    assert decode_output("abc".encode("utf-16-le")) == "abc"
    assert decode_output(b"") == ""
    # 不可解码字节 → replace 回退，不抛错
    assert decode_output(b"\xff\xfe\xfe\xff\x00") != ""
