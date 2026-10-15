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


def _ops(stop_rc=0, stop_out=''):
    """造一个只在内存里跑的 ServiceOps：子进程调用与轮询全部伪造。"""
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
    ops.wait_service = lambda name, target, timeout, **kw: 'STOPPED'
    ops.wait_service_running = lambda name, timeout=25: (True, '4 RUNNING', 4242)
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


def test_whole_stack_restart_is_two_phase_stop_then_start():
    """整栈重启必须两阶段：先逆序全停，再原序全起（绝不逐服务 stop→start）。

    逐服务 stop→start 会让依赖方（erp-prod/erp-arq）先回 RUNNING，等轮到被依赖的
    erp-redis / erp-redis-broker 时，SCM 以「停止控制被发送到其他正在运行的服务所
    依赖的服务」拒停（_SVC_DEPENDS 写成了 DependOnService）→ nssm stop 返回非零、
    Redis 从未停过，其「重启」静默 no-op。两阶段先逆序全停（依赖方先停，不挡被依赖
    者），再原序全起（被依赖者先起，与 SCM 开机序一致）。
    """
    ops, _q = _ops()
    ops.service_cmd_sync('restart')
    calls = [(c[1], c[2]) for c in ops.calls]
    n = len(_SVC_ALL)
    verbs = [c[1] for c in ops.calls]
    assert verbs == ['stop'] * n + ['start'] * n, f'必须整段停、整段起，实际 {verbs}'
    assert calls[:n] == [('stop', name) for name in reversed(_SVC_ALL)], '停机阶段须逆序（依赖方在前）'
    assert calls[n:] == [('start', name) for name in _SVC_ALL], '启动阶段须原序（被依赖者先起）'
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
