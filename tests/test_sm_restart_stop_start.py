"""重启链路回归锁：必须「先停后起」，且 start **无条件**执行。

背景（2026-10-13 现场）
----------------------
用户点『重启』后 erp-prod 停在 STOPPED，Windows 事件日志里**只有 STOP 控制、
没有 START 控制**。根因：原实现把重启交给 `nssm restart`，而 NSSM 2.24 的
restart 实现是

    int ret = control_service(SERVICE_CONTROL_STOP, ...);
    if (ret) nssm_exit(ret);                  // ← 停机返回非 0 就退出
    nssm_exit(control_service(START, ...));   // ← start 根本没发出

（nssm.cpp:271-275）。停机阶段一旦失败（被管进程收尾超出 NSSM 停机预算
AppStopMethodConsole/Threads 各 1500ms 时就会），服务永远停在 STOPPED；而本模块
还吞掉了 nssm 的返回码与输出，只剩一句「25s 内未进入 RUNNING」，无从定位。
2026-10-12 17:34 / 20:58、2026-10-13 08:12 三次复现，每次都得手点『启动』才恢复。

本文件只伪造 run_capture / wait_service*，不碰真实 NSSM、不 import tkinter。
"""
from pathlib import Path

from server_manager.constants import _SVC_ALL
from server_manager.service_ops import ServiceOps

NSSM = r'C:\nssm\nssm.exe'


class _Gate:
    def checkpoint(self):
        pass


class _Recorder:
    """假的 msg_queue：只收 log/hosting_refresh 消息。"""

    def __init__(self):
        self.msgs = []

    def put(self, item):
        self.msgs.append(item)

    def texts(self):
        return [d.get('text', '') for kind, d in self.msgs if kind == 'log']


def _ops(stop_rc=0, stop_out='', *, real_wait_running=False):
    """造一个只在内存里跑的 ServiceOps：子进程调用与轮询全部伪造。

    ``real_wait_running=True`` 时不伪造 ``wait_service_running`` —— 供「PID 未变 =
    本次重启未生效」这类要跑真实判定逻辑的用例。``svc_pid`` 一律伪造：PID 探测与
    本文件关心的启停时序正交，不该真跑 ``sc queryex`` 污染 ``ops.calls``。
    """
    q = _Recorder()
    ops = ServiceOps(q, _Gate(), Path('D:/erp_system'), lambda *a, **k: None)
    ops.find_nssm = lambda: NSSM
    ops.calls = []

    def fake_run(args, timeout=20):
        ops.calls.append(list(args))
        if args[1] == 'stop':
            return stop_rc, stop_out
        return 0, ''

    ops.run_capture = fake_run
    ops.svc_pid = lambda name: None
    ops.wait_service = lambda name, target, timeout, **kw: 'STOPPED'
    if not real_wait_running:
        ops.wait_service_running = lambda name, timeout=25, prev_pid=None: (True, '4 RUNNING', 4242)
    return ops, q


def test_restart_uses_stop_then_start_and_never_nssm_restart():
    """重启 = 显式 stop + start；`nssm restart` 这个坑不能再回去。"""
    ops, _q = _ops()
    ok, _state, pid = ops.restart_service_via_stop_start('erp-prod')
    assert ok is True and pid == 4242
    verbs = [c[1] for c in ops.calls]
    assert verbs == ['stop', 'start'], f'必须显式先停后起，实际 {verbs}'
    assert 'restart' not in verbs, 'nssm restart 停机失败会跳过 start，不得使用'


def test_start_still_issued_when_stop_reports_failure():
    """★ 核心回归：停机阶段返回非 0 **不得**拦掉 start。"""
    ops, _q = _ops(stop_rc=1, stop_out='erp-prod: STOP: 服务无法接受控制信息。')
    ok, _state, _pid = ops.restart_service_via_stop_start('erp-prod')
    assert ok is True, '停机报错也必须继续把服务拉起来'
    assert [c[1] for c in ops.calls] == ['stop', 'start']


def test_stop_failure_is_surfaced_with_its_message():
    """停机非零返回必须如实告警并带上 nssm 原文，否则故障无据可查。"""
    ops, q = _ops(stop_rc=1, stop_out='erp-prod: STOP: 服务无法接受控制信息。')
    ops.restart_service_via_stop_start('erp-prod')
    warns = [t for t in q.texts() if 'stop 返回非零' in t]
    assert warns, f'缺停机失败告警，实际日志={q.texts()}'
    assert '服务无法接受控制信息' in warns[0], '告警必须带上 nssm 的原始输出'


def test_whole_stack_restart_covers_every_service_with_stop_start():
    """整栈重启：每个受管服务各走一次 stop→start，顺序不变。"""
    ops, _q = _ops()
    ops.service_cmd_sync('restart')
    pairs = [(c[1], c[2]) for c in ops.calls]
    assert pairs == [v for name in _SVC_ALL for v in (('stop', name), ('start', name))]
    assert not [c for c in ops.calls if c[1] == 'restart']


def test_restart_clears_ports_before_stopping_and_starting():
    """重启前必须先清端口。

    :5002 若被**非受管**进程占着（历史孤儿后端、GUI 开发栈顶着），新后端绑不上会
    立刻崩、NSSM 再把监督器拉起 —— 服务状态照样 RUNNING、界面照样报「启动成功」，
    ERP 实际不可用（假成功）。清端口能力由 app 注入（与 DevModeOps 同一注入方式）。
    """
    ops, _q = _ops()
    order: list[str] = []
    ops._release_ports = lambda: order.append('clean_ports')
    real_run = ops.run_capture

    def recording_run(args, timeout=20):
        order.append(args[1])
        return real_run(args, timeout)

    ops.run_capture = recording_run
    ops.restart_one_service('erp-prod')
    assert order[0] == 'clean_ports', f'必须先清端口，实际 {order}'
    assert order[1:] == ['stop', 'start'], f'清理后应 stop→start，实际 {order[1:]}'


def test_restart_skips_port_cleanup_when_not_injected():
    """未注入清端口能力时不得报错（纯逻辑调用方 / 旧调用点）。"""
    ops, _q = _ops()
    assert ops._release_ports is None
    ok, _state, _pid = ops.restart_one_service('erp-prod')
    assert ok is True


def test_unconfirmed_stop_is_reported_not_silent():
    """停机没等到 STOPPED 必须如实告警（否则停机阶段的超时完全静默）。"""
    ops, q = _ops()
    ops.wait_service = lambda name, target, timeout, **kw: '3 STOP_PENDING'
    ops.restart_one_service('erp-prod')
    warns = [t for t in q.texts() if '未确认 STOPPED' in t]
    assert warns, f'停机未确认必须告警，实际日志={q.texts()}'
    assert '仍继续启动' in warns[0], '告警须说明仍会继续启动，避免与后续「启动成功」自相矛盾'


def test_restart_flags_noop_when_stop_never_took_effect():
    """停机被 SCM 拒（依赖方在跑）→ PID 不变 → 必须报「未生效」，不得只报「启动成功」。

    erp-redis / erp-redis-broker 有依赖方（erp-prod / erp-arq）：全栈重启轮到它们时，
    依赖方已重启回 RUNNING，SCM 拒停 → 服务从未停过（2026-10-15 现场：PID 18792 全程未变）。
    若只报「启动成功」，运维会以为配置已生效（改 redis.conf 后点重启的典型场景）——假成功。
    """
    ops, q = _ops(
        stop_rc=1,
        stop_out='erp-redis: STOP: 停止控制被发送到其他正在运行的服务所依赖的服务。',
        real_wait_running=True,
    )
    ops.svc_pid = lambda name: 18792      # 停前停后同一 PID：从未停成
    ops.wait_service = lambda name, target, timeout, **kw: '4 RUNNING'
    ok, _state, pid = ops.restart_service_via_stop_start('erp-redis')
    assert ok is True and pid == 18792
    texts = q.texts()
    assert any('未生效' in t for t in texts), f'停机未生效必须报「未生效」，实际={texts}'
    assert not any('启动成功' in t for t in texts), f'PID 未变时不得只报「启动成功」，实际={texts}'


def test_restart_reports_success_when_pid_changes():
    """真实重启（PID 变了）仍报「启动成功」——防新判定把正常重启也误判成未生效。"""
    ops, q = _ops(real_wait_running=True)
    pids = iter([111, 222])               # 停前 111 → 停后 222
    ops.svc_pid = lambda name: next(pids)
    ops.wait_service = lambda name, target, timeout, **kw: '4 RUNNING'
    ok, _state, pid = ops.restart_service_via_stop_start('erp-prod')
    assert ok is True and pid == 222
    texts = q.texts()
    assert any('启动成功' in t for t in texts), texts
    assert not any('未生效' in t for t in texts), texts


def test_start_already_running_localized_is_not_a_warning():
    """中文 nssm 输出「服务的实例已在运行中。」不含 1056/already，不得误报 WARNING。"""
    ops, q = _ops()
    ops.run_capture = lambda args, timeout=20: (1, 'erp-redis: START: 服务的实例已在运行中。')
    ops.start_one_service('erp-redis')
    texts = q.texts()
    assert any('已在运行中，跳过 start' in t for t in texts), f'应识别为已在运行，实际={texts}'
    assert not any('返回非零' in t for t in texts), f'不得误报非零 WARNING，实际={texts}'


def test_start_timeout_localized_is_not_a_warning():
    """中文 1053「服务没有及时响应启动或控制请求。」属超时类，以轮询为准，不报 WARNING。"""
    ops, q = _ops()
    ops.run_capture = lambda args, timeout=20: (1, 'erp-redis: START: 服务没有及时响应启动或控制请求。')
    ops.start_one_service('erp-redis')
    texts = q.texts()
    assert not any('返回非零' in t for t in texts), f'1053 超时类不得报 WARNING，实际={texts}'
