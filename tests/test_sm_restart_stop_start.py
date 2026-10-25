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

import pytest

from server_manager import git_guard
from server_manager.constants import _SVC_ALL, _SVC_REDIS_BROKER, _SVC_REVERSE, _SVC_START_ORDER, _SVC_WEB
from server_manager.service_ops import ServiceOps, ServiceRunResult

NSSM = r'C:\nssm\nssm.exe'


@pytest.fixture(autouse=True)
def _allow_branch_guard(monkeypatch):
    """2026-10-18 OCR 评审：重启闸门会读取真实分支，测试必须打桩（CI 在 PR 分支跑）。"""
    monkeypatch.setattr(git_guard, 'check_production_branch', lambda *a, **k: (True, 'test'))


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
    ops.svc_pid_ex = lambda name: (None, True)
    ops.wait_service = lambda name, target, timeout, **kw: 'STOPPED'
    if not real_wait_running:
        ops.wait_service_running = lambda name, timeout=25, prev_pid=None: ServiceRunResult(
            True, '4 RUNNING', 4242, True)
    return ops, q


def test_restart_uses_stop_then_start_and_never_nssm_restart():
    """重启 = 显式 stop + start；`nssm restart` 这个坑不能再回去。"""
    ops, _q = _ops()
    res = ops.restart_service_via_stop_start('erp-prod')
    assert res.ok is True and res.effective is True and res.pid == 4242
    verbs = [c[1] for c in ops.calls]
    assert verbs == ['stop', 'start'], f'必须显式先停后起，实际 {verbs}'
    assert 'restart' not in verbs, 'nssm restart 停机失败会跳过 start，不得使用'


def test_start_still_issued_when_stop_reports_failure():
    """★ 核心回归：停机阶段返回非 0 **不得**拦掉 start。"""
    ops, _q = _ops(stop_rc=1, stop_out='erp-prod: STOP: 服务无法接受控制信息。')
    res = ops.restart_service_via_stop_start('erp-prod')
    assert res.ok is True, '停机报错也必须继续把服务拉起来'
    assert [c[1] for c in ops.calls] == ['stop', 'start']


def test_stop_failure_is_surfaced_with_its_message():
    """停机非零返回必须如实告警并带上 nssm 原文，否则故障无据可查。"""
    ops, q = _ops(stop_rc=1, stop_out='erp-prod: STOP: 服务无法接受控制信息。')
    ops.restart_service_via_stop_start('erp-prod')
    warns = [t for t in q.texts() if 'stop 返回非零' in t]
    assert warns, f'缺停机失败告警，实际日志={q.texts()}'
    assert '服务无法接受控制信息' in warns[0], '告警必须带上 nssm 的原始输出'


def test_whole_stack_restart_is_two_phase_stop_then_start():
    """整栈重启必须两阶段：先全停，再按启动序全起（绝不逐服务 stop→start）。

    逐服务 stop→start 会让依赖方（erp-prod/erp-arq）先回 RUNNING，等轮到被依赖的
    erp-redis / erp-redis-broker 时，SCM 以「停止控制被发送到其他正在运行的服务所
    依赖的服务」拒停（_SVC_DEPENDS 写成了 DependOnService）→ nssm stop 返回非零、
    Redis 从未停过，其「重启」静默 no-op。两阶段先全停，再按 _SVC_START_ORDER 全起
    （被依赖者先起）。

    ★ 2026-10-16 修正：停机序断言此前写的是 ``reversed(_SVC_ALL)`` —— 那正是实机
      事故根因（字面逆序把被依赖的 broker 顶到第一位，撞上还在跑并持有 6380 连接的
      erp-arq，SCM 以 1051 拒停，停机整段空转 20s 超时后仍照常启动，arq 重连把
      broker 永久钉死）。停机序改按 _SVC_DEPENDS 逆拓扑（依赖方在前），此处随之
      更新为锁 _SVC_REVERSE —— 顺序本身由 test_sm_restart_stop_order.py 锁正确性。
    ★ 2026-10-16（OCR finding）：启动侧同步改为 _SVC_START_ORDER（= _SVC_REVERSE
      逆序，被依赖者先起）。原断言锁的 ``_SVC_ALL`` 是「依赖方在前」的停机序，
      拿它启动会把 erp-arq 排在 erp-redis-broker 之前 → 复现 6380 抢连成环。
    """
    ops, _q = _ops()
    ops.service_cmd_sync('restart')
    calls = [(c[1], c[2]) for c in ops.calls]
    n = len(_SVC_ALL)
    verbs = [c[1] for c in ops.calls]
    assert verbs == ['stop'] * n + ['start'] * n, f'必须整段停、整段起，实际 {verbs}'
    assert calls[:n] == [('stop', name) for name in _SVC_REVERSE], '停机阶段须逆拓扑（依赖方在前）'
    assert calls[n:] == [('start', name) for name in _SVC_START_ORDER], '启动阶段须按 _SVC_START_ORDER（被依赖者先起）'
    assert not [c for c in ops.calls if c[1] == 'restart']


def test_restart_aborts_when_a_service_refuses_to_stop():
    """停机失败必须中止本轮重启，不得重新启动失败的服务（2026-10-16 实机事故）。

    broker 停不掉却照常启动 → arq 重连 6380 把 broker 永久钉死 → 下次重启同样失败
    （自锁循环）。实机指纹：erp-redis-broker stop 返回 1051、20s 内未确认 STOPPED，
    而日志里紧跟着是「正在启动生产服务 erp-arq...」。

    ★ 中止≠全体不起：停机是逆拓扑（被依赖者最后停），中止发生在中间时**已停掉的都是
      前面的依赖方**（prod/arq/web/cache）。不把它们拉回来 ERP 就整体下线，而故障只是
      「某个被依赖服务停不掉」。故断言的是：失败的那个**不得**被启动，其余已停服务应恢复。
    """
    ops, q = _ops()
    real_wait = ops.wait_service

    def wait_stuck(name, target, timeout, **kw):
        if name == _SVC_REDIS_BROKER and target == 'STOPPED':
            return '4 RUNNING'
        return real_wait(name, target, timeout, **kw)

    ops.wait_service = wait_stuck
    # 已停服务(start 才发得出去)：broker 之外的四个都视为已停
    def state(name):
        return '4 RUNNING' if name == _SVC_REDIS_BROKER else '1 STOPPED'

    ops.svc_state = state
    ops.service_cmd_sync('restart')
    started = [c[2] for c in ops.calls if c[1] == 'start']
    assert _SVC_REDIS_BROKER not in started, \
        f'停机失败的服务绝不能被启动（自锁循环），实际启动了: {started}'
    warns = [d for _k, d in q.msgs if d.get('level') == 'WARNING']
    assert any('中止本轮重启' in d['text'] for d in warns), \
        f'必须如实告警已中止重启，实际告警: {[d["text"][:40] for d in warns]}'


def test_restart_abort_restores_already_stopped_services():
    """中止时必须恢复已停服务，否则只是「broker 停不掉」却让整套 ERP 下线。"""
    ops, _q = _ops()
    real_wait = ops.wait_service

    def wait_stuck(name, target, timeout, **kw):
        if name == _SVC_REDIS_BROKER and target == 'STOPPED':
            return '4 RUNNING'
        return real_wait(name, target, timeout, **kw)

    ops.wait_service = wait_stuck
    ops.svc_state = lambda name: '4 RUNNING' if name == _SVC_REDIS_BROKER else '1 STOPPED'
    ops.service_cmd_sync('restart')
    started = [c[2] for c in ops.calls if c[1] == 'start']
    for name in _SVC_ALL:
        if name == _SVC_REDIS_BROKER:
            continue
        assert name in started, f'已停的 {name} 必须被恢复启动（否则 ERP 无故下线），实际启动 {started}'


def test_restart_abort_attempts_start_when_state_unknown():
    """中止恢复时，状态不可确认（'未知' / STOP_PENDING）的服务也要尝试拉起，不得静默丢弃。

    OCR finding（2026-10-16）：恢复循环若只在 svc_state 恰为 'STOPPED' 时才 start，
    则 '未知'（sc 被拦/超时——正是刚导致中止的探针通道）与 STOP_PENDING 会无 start、
    无日志地掉队，服务留在 STOPPED，与「把现场还原成全部在跑」相悖。
    """
    ops, q = _ops()
    real_wait = ops.wait_service

    def wait_stuck(name, target, timeout, **kw):
        if name == _SVC_REDIS_BROKER and target == 'STOPPED':
            return '4 RUNNING'
        return real_wait(name, target, timeout, **kw)

    ops.wait_service = wait_stuck

    def state(name):
        if name == _SVC_REDIS_BROKER:
            return '4 RUNNING'
        if name == _SVC_WEB:
            return '未知'
        return '1 STOPPED'

    ops.svc_state = state
    ops.service_cmd_sync('restart')
    started = [c[2] for c in ops.calls if c[1] == 'start']
    assert _SVC_WEB in started, f'状态不可确认的 {_SVC_WEB} 也必须尝试拉起，实际启动 {started}'
    warns = [d for _k, d in q.msgs if d.get('level') == 'WARNING']
    assert any('状态不可确认' in d['text'] for d in warns), \
        f'状态不可确认时必须告警，实际 {[d["text"][:40] for d in warns]}'


def test_restart_abort_skips_not_installed_services():
    """中止恢复时，'未安装'（sc 1060）的服务无可恢复，不得被 start（否则 1060 + 白等 25s）。"""
    ops, _q = _ops()
    real_wait = ops.wait_service

    def wait_stuck(name, target, timeout, **kw):
        if name == _SVC_REDIS_BROKER and target == 'STOPPED':
            return '4 RUNNING'
        return real_wait(name, target, timeout, **kw)

    ops.wait_service = wait_stuck

    def state(name):
        if name == _SVC_REDIS_BROKER:
            return '4 RUNNING'
        if name == _SVC_WEB:
            return '未安装'
        return '1 STOPPED'

    ops.svc_state = state
    ops.service_cmd_sync('restart')
    started = [c[2] for c in ops.calls if c[1] == 'start']
    assert _SVC_WEB not in started, f"未安装的 {_SVC_WEB} 不该被 start，实际 {started}"


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
    res = ops.restart_one_service('erp-prod')
    assert res.ok is True and res.effective is True


def test_unconfirmed_stop_is_reported_not_silent():
    """停机没等到 STOPPED 必须如实告警（否则停机阶段的超时完全静默）。"""
    ops, q = _ops()
    ops.wait_service = lambda name, target, timeout, **kw: '3 STOP_PENDING'
    ops.restart_one_service('erp-prod')
    warns = [t for t in q.texts() if '未确认 STOPPED' in t]
    assert warns, f'停机未确认必须告警，实际日志={q.texts()}'
    assert '仍继续启动' in warns[0], '告警须说明仍会继续启动，避免与后续「启动成功」自相矛盾'


def test_restart_same_pid_is_ok_but_never_effective():
    """B1 核心锁：停机被 SCM 拒（依赖方在跑）→ PID 不变 → ok=True 但 effective=False。

    erp-redis / erp-redis-broker 有依赖方（erp-prod / erp-arq）：全栈重启轮到它们时，
    依赖方已重启回 RUNNING，SCM 拒停 → 服务从未停过（2026-10-15 现场：PID 18792 全程未变）。
    若只报「启动成功」，运维会以为配置已生效（改 redis.conf 后点重启的典型场景）。
    2026-10-25 上线前检查 B1：同 PID 旧进程健康仍被当发布成功——发布验收消费方
    必须同时要求 ok and effective，本用例锁 effective=False，脚本侧才可能非零退出。
    """
    ops, q = _ops(
        stop_rc=1,
        stop_out='erp-redis: STOP: 停止控制被发送到其他正在运行的服务所依赖的服务。',
        real_wait_running=True,
    )
    ops.svc_pid_ex = lambda name: (18792, True)  # 停前停后同一 PID：从未停成
    ops.wait_service = lambda name, target, timeout, **kw: '4 RUNNING'
    res = ops.restart_service_via_stop_start('erp-redis')
    assert res.ok is True, '服务确实在跑（旧进程），ok 仍为真'
    assert res.effective is False, '同 PID = 重启未发生，绝不能判定 effective'
    assert res.pid == 18792
    texts = q.texts()
    assert any('未生效' in t for t in texts), f'停机未生效必须报「未生效」，实际={texts}'
    assert not any('启动成功' in t for t in texts), f'PID 未变时不得只报「启动成功」，实际={texts}'


def test_restart_with_unreadable_pid_is_never_effective():
    """B1：新 PID 读不出来（探测通道故障）时身份未经证实，effective 必须为 False。

    宁可误报（让运维手查一次），不可漏报（把旧进程当新版本发布）。
    """
    ops, q = _ops(real_wait_running=True)
    pids = iter([(111, True), (None, True)])  # 停前 111 → 停后 RUNNING 却无 PID（身份未证实）
    ops.svc_pid_ex = lambda name: next(pids)
    ops.wait_service = lambda name, target, timeout, **kw: '4 RUNNING'
    res = ops.restart_service_via_stop_start('erp-prod')
    assert res.ok is True and res.pid is None and res.effective is False
    texts = q.texts()
    assert any('无法验证本次重启是否生效' in t for t in texts), texts


def test_restart_reports_success_when_pid_changes():
    """真实重启（PID 变了）仍报「启动成功」且 effective=True——防新判定把正常重启误判成未生效。"""
    ops, q = _ops(real_wait_running=True)
    pids = iter([(111, True), (222, True)])   # 停前 111 → 停后 222
    ops.svc_pid_ex = lambda name: next(pids)
    ops.wait_service = lambda name, target, timeout, **kw: '4 RUNNING'
    res = ops.restart_service_via_stop_start('erp-prod')
    assert res.ok is True and res.effective is True and res.pid == 222
    texts = q.texts()
    assert any('启动成功' in t for t in texts), texts
    assert not any('未生效' in t for t in texts), texts


def test_start_without_prev_pid_is_effective_when_running():
    """纯启动路径（无 prev_pid）不比对 PID：RUNNING 即 effective（如开机首启、崩溃自愈后手拉）。"""
    ops, _q = _ops(real_wait_running=True)
    ops.svc_pid_ex = lambda name: (333, True)  # 无 prev_pid，无从比对，直接生效
    ops.wait_service = lambda name, target, timeout, **kw: '4 RUNNING'
    res = ops.start_one_service('erp-prod')
    assert res.ok is True and res.effective is True and res.pid == 333


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
