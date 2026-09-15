"""`adapters.process_win` 的测试。

本模块承载五条**事故换来的**安全约定（见模块文档），测试逐条守住：

  1. 绝无 shell 参与（参数列表 + 字面量 argv[0]）
  2. 绝不向上杀祖先链
  3. psutil 路径必须与 taskkill /T 同语义（自身 + 全部后代）
  4. 绝不做宽特征兜底
  5. 宁可漏杀，不可误杀
"""

from __future__ import annotations

import pytest

from server_manager_v8.adapters import process_win as P

# ═══════════════════════════════════════════════════════════════════
# 真实 netstat 样本（取自 2026-09-14 采集）
# ═══════════════════════════════════════════════════════════════════

NETSTAT_3000 = """
  TCP    0.0.0.0:3000           0.0.0.0:0              LISTENING       8288
  TCP    [::]:3000              [::]:0                 LISTENING       8288
  TCP    127.0.0.1:54321        127.0.0.1:3000         ESTABLISHED     5936
  TCP    0.0.0.0:30000          0.0.0.0:0              LISTENING       19996
  TCP    127.0.0.1:3000         127.0.0.1:54321        ESTABLISHED     20760
  TCP    127.0.0.1:3000         127.0.0.1:49999        TIME_WAIT       0
"""


class TestTaskkillArgv:
    """约定 1：参数列表 + 字面量 argv[0]，绝无 shell。"""

    def test_force_and_tree_default(self):
        assert P.taskkill_argv(1234) == ['taskkill', '/F', '/T', '/PID', '1234']

    def test_no_force(self):
        assert P.taskkill_argv(1234, force=False) == ['taskkill', '/T', '/PID', '1234']

    def test_no_tree(self):
        assert P.taskkill_argv(1234, tree=False) == ['taskkill', '/F', '/PID', '1234']

    def test_neither(self):
        assert P.taskkill_argv(1234, force=False, tree=False) == ['taskkill', '/PID', '1234']

    def test_pid_coerced_to_int_string(self):
        """防注入：PID 必须是纯数字。"""
        assert P.taskkill_argv('1234') == ['taskkill', '/F', '/T', '/PID', '1234']

    def test_pid_never_string_interpolated(self):
        """★ 若实现改成 f'/PID {pid}' 拼串，下面这条会失败。"""
        argv = P.taskkill_argv(5678)
        assert argv[-2:] == ['/PID', '5678']
        assert not any(' ' in a and a != 'taskkill' for a in argv)

    def test_argv_first_is_literal_taskkill(self):
        assert P.taskkill_argv(1)[0] == 'taskkill'

    def test_float_pid_rejected_by_constructor(self):
        """int() 转换会拒绝非整数（防止传入奇怪对象）。"""
        with pytest.raises((ValueError, TypeError)):
            P.taskkill_argv('not-a-pid')  # type: ignore[arg-type]


class TestKillPid:
    def test_skipped_on_non_windows(self, fake_runner_cls, monkeypatch):
        monkeypatch.setattr(P, 'is_windows', lambda: False)
        runner = fake_runner_cls()
        assert P.kill_pid(1234, runner=runner.run) is False
        assert runner.calls == []

    def test_skipped_for_falsy_pid(self, fake_runner_cls, monkeypatch):
        monkeypatch.setattr(P, 'is_windows', lambda: True)
        runner = fake_runner_cls()
        assert P.kill_pid(0, runner=runner.run) is False
        assert runner.calls == []

    def test_runs_taskkill_on_windows(self, fake_runner_cls, monkeypatch):
        monkeypatch.setattr(P, 'is_windows', lambda: True)
        runner = fake_runner_cls().on(['taskkill', '/F', '/T', '/PID', '1234'], 0)
        assert P.kill_pid(1234, runner=runner.run) is True

    def test_nonzero_exit_returns_false(self, fake_runner_cls, monkeypatch):
        monkeypatch.setattr(P, 'is_windows', lambda: True)
        runner = fake_runner_cls().on(['taskkill', '/F', '/T', '/PID', '1234'], 128)
        assert P.kill_pid(1234, runner=runner.run) is False

    def test_uses_utf8_mode_not_oem(self, fake_runner_cls, monkeypatch):
        """taskkill 自身无有用输出，旧实现用 oem=False（保真）。"""
        monkeypatch.setattr(P, 'is_windows', lambda: True)
        runner = fake_runner_cls().on(['taskkill', '/F', '/T', '/PID', '1'], 0)
        P.kill_pid(1, runner=runner.run)
        kw = runner.kwargs_for(['taskkill', '/F', '/T', '/PID', '1'])
        assert kw['text'] is True
        assert 'encoding' not in kw


class TestKillMany:
    """约定 2 + 3：终止自身 + 全部后代，绝不向上；psutil 与 taskkill /T 同语义。"""

    def test_non_windows_noop(self, monkeypatch):
        monkeypatch.setattr(P, 'is_windows', lambda: False)
        assert P.kill_many([1, 2]).targeted == 0

    def test_empty_pids_noop(self, monkeypatch):
        monkeypatch.setattr(P, 'is_windows', lambda: True)
        assert P.kill_many([]).targeted == 0

    def test_psutil_kills_self_and_all_children(self, fake_runner_cls, monkeypatch):
        """★ v5.40 审查 #4 的核心断言。

        只杀 netstat 报告的单个 PID 是不够的：监听 socket 句柄会被
        --reload supervisor / npm 等父子进程共享继承，单杀一个后其余进程
        仍持有句柄，端口释放 3 轮重试空转后静默失效。
        """
        monkeypatch.setattr(P, 'is_windows', lambda: True)
        from tests.adapters.conftest import FakeProc, process_factory

        child1 = FakeProc(pid=101)
        child2 = FakeProc(pid=102)
        grand = FakeProc(pid=103)
        child1.children_list = [grand]
        root = FakeProc(pid=100, children_list=[child1, child2])

        outcome = P.kill_many([100], process_factory=process_factory([root]))
        assert root.killed and child1.killed and child2.killed and grand.killed
        assert outcome.targeted == 4

    def test_psutil_never_kills_ancestors(self, monkeypatch):
        """★ 约定 2：绝不向上杀祖先链 —— 可能殃及 explorer 等无辜进程。"""
        monkeypatch.setattr(P, 'is_windows', lambda: True)
        from tests.adapters.conftest import FakeProc, process_factory

        ancestor = FakeProc(pid=1, name='explorer.exe')
        root = FakeProc(pid=100, parents_list=[ancestor])

        P.kill_many([100], process_factory=process_factory([root]))
        assert root.killed is True
        assert ancestor.killed is False, '祖先链绝不能被终止'

    def test_dedup_across_overlapping_families(self, monkeypatch):
        """某 PID 的后代可能同时是另一条记录的 PID —— 去重避免重复计数。"""
        monkeypatch.setattr(P, 'is_windows', lambda: True)
        from tests.adapters.conftest import FakeProc, process_factory

        shared = FakeProc(pid=200)
        root = FakeProc(pid=100, children_list=[shared])
        # 同时直接传 shared（它既是后代又是独立记录）
        outcome = P.kill_many([100, 200], process_factory=process_factory([root, shared]))
        assert outcome.targeted == 2

    def test_missing_process_falls_back_to_taskkill(self, fake_runner_cls, monkeypatch):
        """进程已退出 → psutil.Process 抛异常 → 退回 taskkill（旧行为）。"""
        monkeypatch.setattr(P, 'is_windows', lambda: True)
        from tests.adapters.conftest import process_factory

        runner = fake_runner_cls().on(['taskkill', '/F', '/T', '/PID', '999'], 128)
        P.kill_many([999], runner=runner.run,
                    process_factory=process_factory([], missing={999}))
        assert runner.called_with(['taskkill', '/F', '/T', '/PID', '999'])

    def test_kill_exception_does_not_abort_batch(self, monkeypatch):
        """单个 kill 抛异常（如权限）不该中断整批。"""
        monkeypatch.setattr(P, 'is_windows', lambda: True)
        from tests.adapters.conftest import FakeProc, process_factory

        bad = FakeProc(pid=1, kill_raises=True)
        good = FakeProc(pid=2)
        P.kill_many([1, 2], process_factory=process_factory([bad, good]))
        assert good.killed is True

    def test_backend_reported_as_psutil(self, monkeypatch):
        monkeypatch.setattr(P, 'is_windows', lambda: True)
        from tests.adapters.conftest import FakeProc, process_factory

        P.kill_many([1], process_factory=process_factory([FakeProc(pid=1)]))
        assert P.kill_many([2], process_factory=process_factory([FakeProc(pid=2)])).backend == 'psutil'

    def test_falls_back_to_taskkill_without_psutil(self, fake_runner_cls, monkeypatch):
        monkeypatch.setattr(P, 'is_windows', lambda: True)
        monkeypatch.setattr(P, 'psutil', None)
        runner = fake_runner_cls().on(['taskkill', '/F', '/T', '/PID', '7'], 0)
        outcome = P.kill_many([7], runner=runner.run)
        assert outcome.backend == 'taskkill'
        assert runner.called_with(['taskkill', '/F', '/T', '/PID', '7'])


class TestKillTree:
    def test_windows_uses_taskkill(self, fake_runner_cls, monkeypatch):
        monkeypatch.setattr(P, 'is_windows', lambda: True)
        runner = fake_runner_cls().on(['taskkill', '/F', '/T', '/PID', '42'], 0)
        assert P.kill_tree(42, runner=runner.run) is True

    def test_non_windows_uses_sigterm(self, monkeypatch):
        """★ 非 Windows 分支用 SIGTERM(15) 而非 SIGKILL —— 给进程清理机会。"""
        sent = []
        monkeypatch.setattr(P, 'is_windows', lambda: False)
        monkeypatch.setattr(P.os, 'kill', lambda pid, sig: sent.append((pid, sig)))
        assert P.kill_tree(42) is True
        assert sent == [(42, 15)]

    def test_non_windows_kill_failure_returns_false(self, monkeypatch):
        monkeypatch.setattr(P, 'is_windows', lambda: False)
        monkeypatch.setattr(P.os, 'kill',
                            lambda pid, sig: (_ for _ in ()).throw(ProcessLookupError()))
        assert P.kill_tree(42) is False

    def test_falsy_pid_noop(self, fake_runner_cls):
        runner = fake_runner_cls()
        assert P.kill_tree(0, runner=runner.run) is False
        assert runner.calls == []


# ═══════════════════════════════════════════════════════════════════
# 端口查询 / 清场
# ═══════════════════════════════════════════════════════════════════


class TestPortPids:
    """击杀口径：仅 LISTENING（v5.40 审查 #23）。"""

    def test_only_listening_counted(self, fake_runner_cls):
        runner = fake_runner_cls().on(['netstat', '-ano'], 0, NETSTAT_3000)
        pids, err = P.port_pids(3000, runner=runner.run)
        assert err is None
        # 8288 出现两次（IPv4+IPv6 双栈）→ 去重为 1
        assert pids == ['8288']

    def test_time_wait_excluded(self, fake_runner_cls):
        """★ TIME_WAIT 会自行过期且不阻塞重绑 —— 纳入击杀只会产生多余尝试。"""
        runner = fake_runner_cls().on(['netstat', '-ano'], 0, NETSTAT_3000)
        pids, _ = P.port_pids(3000, runner=runner.run)
        assert '0' not in pids
        assert '20760' not in pids  # ESTABLISHED 不在击杀口径内

    def test_established_excluded_for_kill(self, fake_runner_cls):
        """击杀口径不看 ESTABLISHED（连接方不是占用者）。"""
        runner = fake_runner_cls().on(['netstat', '-ano'], 0, NETSTAT_3000)
        pids, _ = P.port_pids(3000, runner=runner.run)
        assert '5936' not in pids

    def test_substring_false_positive_avoided(self, fake_runner_cls):
        """★ 列位精确匹配：30000 端口的占用者不能算进 3000。"""
        runner = fake_runner_cls().on(['netstat', '-ano'], 0, NETSTAT_3000)
        pids, _ = P.port_pids(3000, runner=runner.run)
        assert '19996' not in pids

    def test_netstat_failure_returns_error_not_silence(self, fake_runner_cls):
        """★ D10：netstat 失败会让端口释放**静默失效** —— 必须返回错误。"""
        runner = fake_runner_cls()
        runner.raise_on(['netstat', '-ano'], OSError('netstat not found'))
        pids, err = P.port_pids(3000, runner=runner.run)
        assert pids == []
        assert err is not None and 'OSError' in err

    def test_uses_oem_decoding(self, fake_runner_cls):
        runner = fake_runner_cls().on(['netstat', '-ano'], 0, '')
        P.netstat_lines(runner=runner.run)
        assert runner.kwargs_for(['netstat', '-ano'])['encoding'] == 'oem'


class TestPortOccupiers:
    """留痕口径：LISTENING 或 ESTABLISHED（v5.40 审查 #6）。"""

    def test_established_included_for_audit(self, fake_runner_cls):
        """★ 与击杀口径刻意不同：连接方也算占用者（v5.40 审查 #6）。

        样本里两条 ESTABLISHED 的**本地端口**不同：
          `127.0.0.1:54321 → 127.0.0.1:3000`  本地端口 54321（3000 是**远端**）
          `127.0.0.1:3000  → 127.0.0.1:54321` 本地端口 3000  ✅
        因此只有 PID 20760 该被计入，5936 不应计入 —— 只看**本地地址列**。
        （这正是旧实现子串匹配的误报②：它会把 5936 也算成 3000 的占用者。）
        """
        runner = fake_runner_cls().on(['netstat', '-ano'], 0, NETSTAT_3000)
        occupiers, err = P.port_occupiers(
            3000, runner=runner.run, name_resolver=lambda pid: f'proc{pid}'
        )
        assert err is None
        pids = {o.pid for o in occupiers}
        assert '8288' in pids    # LISTENING（IPv4 + IPv6 双栈）
        assert '20760' in pids   # ESTABLISHED，本地端口 3000
        assert '5936' not in pids  # ESTABLISHED，但本地端口是 54321（3000 仅为远端）

    def test_remote_address_not_counted(self, fake_runner_cls):
        """★ 回归防护：远端地址列出现目标端口时**不算**占用。"""
        runner = fake_runner_cls().on(['netstat', '-ano'], 0, NETSTAT_3000)
        occupiers, _ = P.port_occupiers(
            3000, runner=runner.run, name_resolver=lambda pid: 'x'
        )
        names_by_pid = {o.pid: o.name for o in occupiers}
        assert '5936' not in names_by_pid

    def test_time_wait_excluded_from_audit(self, fake_runner_cls):
        runner = fake_runner_cls().on(['netstat', '-ano'], 0, NETSTAT_3000)
        occupiers, _ = P.port_occupiers(
            3000, runner=runner.run, name_resolver=lambda pid: 'x'
        )
        assert '0' not in {o.pid for o in occupiers}

    def test_deduplicates_by_pid(self, fake_runner_cls):
        """双栈同一 PID 只留一条（避免留痕刷屏）。"""
        runner = fake_runner_cls().on(['netstat', '-ano'], 0, NETSTAT_3000)
        occupiers, _ = P.port_occupiers(
            3000, runner=runner.run, name_resolver=lambda pid: 'x'
        )
        assert len({o.pid for o in occupiers}) == len(occupiers)

    def test_describe_matches_legacy_wording(self):
        o = P.PortOccupierInfo(3000, '8288', 'node.exe')
        assert o.describe() == '端口 3000 被 node.exe(PID 8288) 占用，即将释放'

    def test_netstat_failure_still_returns_collected(self, fake_runner_cls):
        """保留「尽力而为」的失败语义：失败返回空但带 error，不抛。"""
        runner = fake_runner_cls()
        runner.raise_on(['netstat', '-ano'], OSError('boom'))
        occupiers, err = P.port_occupiers(3000, runner=runner.run)
        assert occupiers == []
        assert err is not None


class TestResolveProcessName:
    def test_parses_csv_name(self, fake_runner_cls):
        runner = fake_runner_cls().on(
            ['tasklist', '/FI', 'PID eq 8288', '/FO', 'CSV', '/NH'], 0,
            '"node.exe","8288","Console","1","120,000 K"'
        )
        assert P.resolve_process_name('8288', runner=runner.run) == 'node.exe'

    def test_failure_gives_unknown_process(self, fake_runner_cls):
        runner = fake_runner_cls()
        runner.raise_on(['tasklist', '/FI', 'PID eq 1', '/FO', 'CSV', '/NH'], OSError())
        assert P.resolve_process_name('1', runner=runner.run) == '未知进程'

    def test_empty_output_gives_unknown_process(self, fake_runner_cls):
        runner = fake_runner_cls().on(
            ['tasklist', '/FI', 'PID eq 1', '/FO', 'CSV', '/NH'], 0, ''
        )
        assert P.resolve_process_name('1', runner=runner.run) == '未知进程'


class TestKillPortSync:
    """迁移自 `_kill_port_sync`（L1089-1096）：3 轮重试。"""

    def test_returns_early_when_no_pids(self, fake_runner_cls, monkeypatch):
        monkeypatch.setattr(P, 'is_windows', lambda: True)
        runner = fake_runner_cls().on(['netstat', '-ano'], 0, '')
        slept = []
        outcome = P.kill_port_sync(3000, sleep=slept.append, runner=runner.run)
        assert outcome.rounds == 1
        assert slept == []

    def test_retries_three_rounds_while_occupied(self, fake_runner_cls, monkeypatch):
        """★ 每轮**重新查询**：被杀进程的句柄可能被兄弟继承，
        重启后端口会出现新占用者，必须重新发现。"""
        monkeypatch.setattr(P, 'is_windows', lambda: True)
        monkeypatch.setattr(P, 'psutil', None)
        runner = fake_runner_cls()
        runner.matching(['netstat', '-ano'], 0, NETSTAT_3000)
        runner.matching(['taskkill'], 0)
        slept = []
        outcome = P.kill_port_sync(3000, sleep=slept.append, runner=runner.run)
        assert outcome.rounds == 3
        assert slept == [0.5, 0.5, 0.5]

    def test_stops_retrying_once_clear(self, fake_runner_cls, monkeypatch):
        """第二轮查不到占用者 → 立即返回，不做无谓的第三轮。"""
        monkeypatch.setattr(P, 'is_windows', lambda: True)
        monkeypatch.setattr(P, 'psutil', None)
        calls = {'n': 0}

        def runner(argv, **kw):
            from types import SimpleNamespace
            if list(argv)[0] == 'netstat':
                calls['n'] += 1
                out = NETSTAT_3000 if calls['n'] == 1 else ''
                return SimpleNamespace(returncode=0, stdout=out, stderr='')
            return SimpleNamespace(returncode=0, stdout='', stderr='')

        slept = []
        outcome = P.kill_port_sync(3000, sleep=slept.append, runner=runner)
        assert outcome.rounds == 2
        assert len(slept) == 1

    def test_non_windows_noop(self, monkeypatch):
        monkeypatch.setattr(P, 'is_windows', lambda: False)
        assert P.kill_port_sync(3000).rounds == 0

    def test_sleep_injectable_so_test_is_fast(self, fake_runner_cls, monkeypatch):
        """sleep 可注入 → 单测不真实等待（与 domain 的假时钟同一原则）。"""
        monkeypatch.setattr(P, 'is_windows', lambda: True)
        monkeypatch.setattr(P, 'psutil', None)
        runner = fake_runner_cls()
        runner.matching(['netstat', '-ano'], 0, NETSTAT_3000)
        runner.matching(['taskkill'], 0)
        slept = []
        P.kill_port_sync(3000, sleep=slept.append, runner=runner.run)
        assert slept == [0.5, 0.5, 0.5]  # 记录到了，但没有真实 sleep


# ═══════════════════════════════════════════════════════════════════
# 残留扫描 —— 约定 4 + 5
# ═══════════════════════════════════════════════════════════════════


class TestResidualCandidate:
    """逐条对应 `_kill_residual`（L1837-1861）的判定链。"""

    def _cand(self, **kw):
        base = dict(pid=1000, cmdline=[], process_name='', cwd='',
                    protected=frozenset(), ancestor_pids=())
        base.update(kw)
        return P.is_residual_candidate(**base)

    def test_protected_pid_rejected(self):
        assert self._cand(pid=1000, protected=frozenset({1000}),
                          cmdline=['python', 'uvicorn', 'fastapi_app'],
                          process_name='python.exe',
                          cwd='d:/erp_system') is False

    def test_falsy_pid_rejected(self):
        assert self._cand(pid=0, cmdline=['uvicorn'], process_name='python.exe',
                          cwd='d:/erp_system') is False

    def test_prod_runner_never_victim(self):
        """★ NSSM 被管业务进程：误杀会被 AppExit 判为崩溃并 5 秒自动重启。"""
        assert self._cand(cmdline=['python', 'prod_runner.py'],
                          process_name='python.exe',
                          cwd='d:/erp_system') is False

    def test_arq_app_never_victim(self):
        assert self._cand(cmdline=['python', 'arq_app.py'],
                          process_name='python.exe',
                          cwd='d:/erp_system') is False

    def test_marker_case_insensitive(self):
        """旧实现用 `.lower()` 后匹配 —— 保真。"""
        assert self._cand(cmdline=['python', 'PROD_RUNNER.PY'],
                          process_name='python.exe',
                          cwd='d:/erp_system') is False

    def test_descendant_of_protected_rejected(self):
        """服务进程的后代同样受保护。"""
        assert self._cand(cmdline=['python', 'uvicorn', 'fastapi_app'],
                          process_name='python.exe', cwd='d:/erp_system',
                          protected=frozenset({500}),
                          ancestor_pids=[500]) is False

    def test_missing_project_marker_rejected(self):
        """★ 约定 4：宽特征必须叠加项目标记，否则会误杀机器上所有 node.exe。"""
        assert self._cand(cmdline=['node', 'vite.js'], process_name='node.exe',
                          cwd='c:/other-project') is False

    def test_project_marker_in_cmdline_accepted(self):
        assert self._cand(cmdline=['node', 'd:/erp_system/frontend-vite/vite.js'],
                          process_name='node.exe', cwd='') is True

    def test_project_marker_in_cwd_accepted(self):
        assert self._cand(cmdline=['node', 'vite.js'], process_name='node.exe',
                          cwd='D:/erp_system/frontend-vite') is True

    def test_uvicorn_with_marker_accepted(self):
        assert self._cand(cmdline=['python', '-m', 'uvicorn', 'fastapi_app.main:app'],
                          process_name='python.exe', cwd='d:/erp_system') is True

    def test_vite_with_marker_accepted(self):
        assert self._cand(cmdline=['node', 'vite'], process_name='node.exe',
                          cwd='d:/erp_system') is True

    def test_python_with_fastapi_app_accepted(self):
        assert self._cand(cmdline=['python', 'fastapi_app/main.py'],
                          process_name='python.exe', cwd='d:/erp_system') is True

    def test_plain_python_with_marker_rejected(self):
        """有项目标记但特征不命中（不是 uvicorn/vite）→ 不杀。"""
        assert self._cand(cmdline=['python', 'manage.py'], process_name='python.exe',
                          cwd='d:/erp_system') is False

    def test_node_process_name_alone_not_enough(self):
        """★ 约定 4：仅 'node' 在进程名里不够，必须有项目标记。

        v5.40 审查 #5：宽特征 'node' in pname 会误杀机器上所有 node.exe
        （编辑器插件等）。
        """
        assert self._cand(cmdline=['node', 'server.js'], process_name='node.exe',
                          cwd='c:/vscode') is False

    def test_no_cmdline_no_cwd_but_node_name_rejected(self):
        assert self._cand(cmdline=None, process_name='node.exe', cwd='') is False

    def test_empty_everything_rejected(self):
        assert self._cand() is False


class TestScanResidual:
    def test_non_windows_skipped(self, monkeypatch):
        monkeypatch.setattr(P, 'is_windows', lambda: False)
        scan = P.scan_residual()
        assert scan.scanned is False
        assert '非 Windows' in scan.skipped_reason

    def test_missing_psutil_skipped_with_reason(self, monkeypatch):
        """★ 约定 4：psutil 缺失 → 记原因并跳过，**绝不降级为宽特征兜底**。

        `scanned=False` 与 `victims=()` 的区别很重要：
        旧实现把两者都表达为「无受害者」，会让运维误以为环境干净。
        """
        monkeypatch.setattr(P, 'is_windows', lambda: True)
        monkeypatch.setattr(P, 'psutil', None)
        scan = P.scan_residual()
        assert scan.scanned is False
        assert '缺少 psutil' in scan.skipped_reason
        assert '不做宽特征兜底' in scan.skipped_reason

    def test_finds_project_processes(self, monkeypatch):
        monkeypatch.setattr(P, 'is_windows', lambda: True)
        from tests.adapters.conftest import FakeProc, process_iter_factory

        procs = [
            FakeProc(pid=100, name='node.exe', cmdline=['node', 'vite'],
                     cwd_value='d:/erp_system/frontend-vite'),
            FakeProc(pid=200, name='python.exe', cmdline=['python', 'uvicorn',
                                                          'fastapi_app:app'],
                     cwd_value='d:/erp_system'),
        ]
        scan = P.scan_residual(process_iter=process_iter_factory(procs))
        assert scan.scanned is True
        assert set(scan.victims) == {100, 200}

    def test_skips_nssm_managed_processes(self, monkeypatch):
        monkeypatch.setattr(P, 'is_windows', lambda: True)
        from tests.adapters.conftest import FakeProc, process_iter_factory

        procs = [
            FakeProc(pid=100, name='python.exe',
                     cmdline=['python', 'prod_runner.py'],
                     cwd_value='d:/erp_system'),
        ]
        scan = P.scan_residual(process_iter=process_iter_factory(procs))
        assert scan.victims == ()

    def test_respects_protected_pids(self, monkeypatch):
        monkeypatch.setattr(P, 'is_windows', lambda: True)
        from tests.adapters.conftest import FakeProc, process_iter_factory

        procs = [
            FakeProc(pid=100, name='python.exe', cmdline=['python', 'uvicorn',
                                                          'fastapi_app'],
                     cwd_value='d:/erp_system'),
        ]
        scan = P.scan_residual(protected=frozenset({100}),
                               process_iter=process_iter_factory(procs))
        assert scan.victims == ()

    def test_cwd_permission_error_treated_as_no_marker(self, monkeypatch):
        """★ 约定 5：cwd 读取失败按无标记处理 → 放行（宁可漏杀，不可误杀）。"""
        monkeypatch.setattr(P, 'is_windows', lambda: True)
        from tests.adapters.conftest import FakeProc, process_iter_factory

        procs = [
            FakeProc(pid=100, name='node.exe', cmdline=['node', 'vite'],
                     cwd_raises=True),
        ]
        scan = P.scan_residual(process_iter=process_iter_factory(procs))
        assert scan.victims == ()

    def test_process_exception_does_not_abort_scan(self, monkeypatch):
        monkeypatch.setattr(P, 'is_windows', lambda: True)

        from tests.adapters.conftest import FakeProc

        class Exploding:
            @property
            def info(self):
                raise RuntimeError('boom')

        procs = [Exploding(), FakeProc(pid=100, name='node.exe',
                                       cmdline=['node', 'vite'],
                                       cwd_value='d:/erp_system')]

        def it(attrs=None):
            return procs

        scan = P.scan_residual(process_iter=it)
        assert 100 in scan.victims

    def test_found_any_property(self, monkeypatch):
        monkeypatch.setattr(P, 'is_windows', lambda: True)
        from tests.adapters.conftest import FakeProc, process_iter_factory

        scan = P.scan_residual(process_iter=process_iter_factory([]))
        assert scan.found_any is False
        scan2 = P.scan_residual(process_iter=process_iter_factory(
            [FakeProc(pid=1, name='node.exe', cmdline=['node', 'vite'],
                      cwd_value='d:/erp_system')]))
        assert scan2.found_any is True

    def test_protected_echoed_back(self, monkeypatch):
        monkeypatch.setattr(P, 'is_windows', lambda: True)
        from tests.adapters.conftest import process_iter_factory

        scan = P.scan_residual(protected=frozenset({1, 2}),
                               process_iter=process_iter_factory([]))
        assert scan.protected == frozenset({1, 2})


class TestHasPsutil:
    def test_returns_bool(self):
        assert isinstance(P.has_psutil(), bool)

    def test_matches_module_state(self):
        assert P.has_psutil() == (P.psutil is not None)
