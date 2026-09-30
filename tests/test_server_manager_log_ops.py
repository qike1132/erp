"""server_manager 日志运维层回归测试（无 Tk、无 NSSM、无真实服务）。

锁定 v5.34 现场的两件事：

1) 「生产模式打开后运行日志不是实时输出」
   生产进程跑在 NSSM 服务里，manager 与它之间**没有 stdout 管道**，只能轮询
   ``logs\\{service}.log`` 的增量。本测试锁定 ProdLogTailer 的四条契约：
   · 接入前的历史绝不回灌（那是上一次运行的旧 PID/旧崩溃栈）；
   · 接入后新增的行必须出现（1s 一轮的增量语义）；
   · 半行要缓冲到换行再出（否则 UTF-8/长输出被切成两半）；
   · 文件被轮转/截断后从头继续，且**不丢**内容（超量只延后，不丢弃）。

2) 「日志功能增加一个定时清理，不然越来越多」
   NSSM 只按 10MB 轮转、从不删除旧副本 ⇒ 保留清理必须真的会删、删得准
   （只碰 ``*.log*``，绝不碰 ``prod_runner.json``/``nginx.pid`` 这类状态文件），
   且删不掉（被占用）时只记 skipped，不能让整轮清理失败。

运行: python -m pytest tests/test_server_manager_log_ops.py -q
"""
import ast
import os
import queue
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server_manager.log_ops import (
    LOG_ALERT_BYTES_PER_DAY,
    LOG_HEALTH_STATE_NAME,
    LOG_ROTATE_BYTES,
    LogHealthReport,
    ProdLogTailer,
    inspect_log_health,
    prune_log_files,
    rotate_file_copytruncate,
    rotate_oversized_logs,
)
from server_manager.log_view import LogViewMixin

PKG = Path(__file__).resolve().parents[1] / 'server_manager'


def _drain(q: queue.Queue) -> list:
    msgs = []
    while not q.empty():
        msgs.append(q.get_nowait())
    return msgs


def _texts(msgs) -> list:
    """把所有 log / log_batch 消息摊平成文本列表。"""
    out = []
    for kind, data in msgs:
        if kind == 'log':
            out.append(data['text'])
        elif kind == 'log_batch':
            out.extend(data['lines'])
    return out


def _levels(msgs) -> dict:
    """行文本 → 级别（log_batch 一行一个元素，级别是全批共用的）。"""
    out = {}
    for kind, data in msgs:
        if kind == 'log':
            out[data['text']] = data.get('level', 'INFO')
        elif kind == 'log_batch':
            for line in data['lines']:
                out[line] = data.get('level', 'INFO')
    return out


class _Writer:
    """构造一个「生产环境」日志目录：只有文件，没有进程。"""

    def __init__(self, tmp_path: Path, services=('erp-prod', 'erp-arq')):
        self.log_dir = tmp_path / 'logs'
        self.log_dir.mkdir()
        self.queue = queue.Queue()
        self.tailer = ProdLogTailer(self.queue, tmp_path, services=services)
        self.services = services

    def append(self, name: str, text: str):
        with open(self.log_dir / f'{name}.log', 'ab') as fh:
            fh.write(text.encode('utf-8'))


class TestTailerRealtime:
    def test_attach_does_not_replay_history(self, tmp_path):
        """接入前的历史（上次运行的旧输出）绝不倒出来 —— 起点取当前 EOF。"""
        w = _Writer(tmp_path)
        for name in w.services:
            w.append(name, 'LAST RUN crash PID 99999\n')
        assert w.tailer.ensure_started() is True
        w.tailer.poll_once()
        texts = _texts(_drain(w.queue))          # 只有接入提示
        assert not any('LAST RUN' in t for t in texts)
        assert len(texts) == 1 and '已接入生产日志实时输出' in texts[0]
        w.tailer.stop()

    def test_new_lines_stream_after_attach(self, tmp_path):
        w = _Writer(tmp_path)
        w.tailer.ensure_started()
        _drain(w.queue)
        w.append('erp-prod', 'INFO: Started server 5002\n')
        w.append('erp-arq', 'worker ready\n')
        w.tailer.poll_once()
        texts = _texts(_drain(w.queue))
        assert '[erp-prod] INFO: Started server 5002' in texts
        assert '[erp-arq] worker ready' in texts
        w.tailer.stop()

    def test_partial_line_is_buffered_until_newline(self, tmp_path):
        """写入方还没写完整行时不能把半截行吐到界面（日志是逐行追加写的）。"""
        w = _Writer(tmp_path, services=('erp-prod',))
        w.tailer.ensure_started()
        _drain(w.queue)
        w.append('erp-prod', 'half')
        w.tailer.poll_once()
        assert _texts(_drain(w.queue)) == []
        w.append('erp-prod', '-line done\n')
        w.tailer.poll_once()
        assert '[erp-prod] half-line done' in _texts(_drain(w.queue))
        w.tailer.stop()

    def test_rotation_in_place_truncate_keeps_streaming(self, tmp_path):
        """就地截断（copytruncate）后从头继续，并如实说明轮转。"""
        w = _Writer(tmp_path, services=('erp-prod',))
        w.tailer.ensure_started()
        w.append('erp-prod', 'old-1\nold-2\n')
        w.tailer.poll_once()
        _drain(w.queue)
        (w.log_dir / 'erp-prod.log').write_bytes(b'new\n')
        w.tailer.poll_once()
        texts = _texts(_drain(w.queue))
        assert any('已轮转' in t for t in texts)
        assert '[erp-prod] new' in texts
        w.tailer.stop()

    def test_rotation_rename_away_is_detected_even_if_new_file_is_bigger(self, tmp_path):
        """NSSM 按大小轮转 = 旧文件改名 + 新文件从 0 写。

        新文件可能已经长过旧 offset —— 只比大小会静默吞掉新文件开头几行，
        必须靠文件句柄号换成新文件来判定。
        """
        w = _Writer(tmp_path, services=('erp-prod',))
        w.tailer.ensure_started()
        w.append('erp-prod', 'old-1\nold-2\n')          # 12 字节 → offset=12
        w.tailer.poll_once()
        _drain(w.queue)
        log = w.log_dir / 'erp-prod.log'
        os.replace(log, w.log_dir / 'erp-prod.log.20260930')   # 轮转：改名
        log.write_bytes(b'BRAND-NEW-START-LINE\n')             # 新文件，比旧 offset 长
        w.tailer.poll_once()
        texts = _texts(_drain(w.queue))
        assert any('已轮转' in t for t in texts)
        assert '[erp-prod] BRAND-NEW-START-LINE' in texts      # 没有被吞掉头部
        w.tailer.stop()

    def test_burst_over_cap_is_deferred_not_dropped(self, tmp_path):
        """单轮回灌有上限（防 UI 卡顿），但超量部分只延后一轮，绝不丢内容。"""
        w = _Writer(tmp_path, services=('erp-prod',))
        w.tailer.ensure_started()
        _drain(w.queue)
        total = ProdLogTailer.MAX_LINES_PER_POLL + 50
        w.append('erp-prod', ''.join(f'line-{i}\n' for i in range(total)))
        w.tailer.poll_once()
        first = [t for t in _texts(_drain(w.queue)) if t.startswith('[erp-prod] line-')]
        assert len(first) == ProdLogTailer.MAX_LINES_PER_POLL
        w.tailer.poll_once()
        second = [t for t in _texts(_drain(w.queue)) if t.startswith('[erp-prod] line-')]
        assert len(first) + len(second) == total
        assert len(set(first) | set(second)) == total      # 无重复、无丢失
        w.tailer.stop()

    def test_error_lines_are_classified_for_coloring(self, tmp_path):
        w = _Writer(tmp_path, services=('erp-prod',))
        w.tailer.ensure_started()
        _drain(w.queue)
        w.append('erp-prod', 'Traceback (most recent call last):\n')
        w.tailer.poll_once()
        levels = _levels(_drain(w.queue))
        assert levels['[erp-prod] Traceback (most recent call last):'] == 'ERROR'
        w.tailer.stop()

    def test_ensure_started_is_idempotent(self, tmp_path):
        """每轮托管刷新都会调 ensure_started —— 重复调用不得重复起线程/重复提示。"""
        w = _Writer(tmp_path)
        assert w.tailer.ensure_started() is True
        assert w.tailer.ensure_started() is False
        assert w.tailer.running is True
        assert sum('已接入' in t for t in _texts(_drain(w.queue))) == 1
        assert w.tailer.stop() is True
        assert w.tailer.running is False
        assert w.tailer.stop() is False

    def test_missing_log_file_is_tolerated(self, tmp_path):
        """服务还没起过（日志文件不存在）时轮询不得抛异常。"""
        w = _Writer(tmp_path)
        w.tailer.ensure_started()
        w.tailer.poll_once()
        assert w.tailer.running is True
        w.tailer.stop()


def _write_log(path: Path, size: int, age_days: float, now: float):
    path.write_bytes(b'x' * size)
    stamp = now - age_days * 86400
    os.utime(path, (stamp, stamp))
    return path


def _func_src(rel_path: str, name: str) -> str:
    """按 AST 取指定模块内某函数/方法的源码段（不依赖模块顺序，也不靠字符串撞运气）。"""
    src = (PKG / rel_path).read_text(encoding='utf-8')
    lines = src.splitlines()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return '\n'.join(lines[node.lineno - 1:node.end_lineno])
    raise AssertionError(f'{rel_path} 内未找到 {name}')


class TestAppWiring:
    """接线锁：机制写对了但没接进运行时，用户看到的还是「日志不实时、文件越攒越多」。

    本层是**唯一**会被「重构时顺手动一下」拉断的地方（机制层有上面的 15 例守着），
    故按仓库惯例（test_sm_workers_apply）用 AST 锁调用点。
    """

    def test_start_flow_attaches_tailer_after_replay(self):
        body = _func_src('app.py', '_start_services_flow')
        assert 'prod_logs.ensure_started()' in body, \
            '启动服务流程未接入实时回灌 —— 一次性回灌之后界面会再次归于安静'

    def test_hosting_refresh_drives_tailer_both_ways(self):
        body = _func_src('hosting_view.py', '_apply_hosting_data')
        assert '_sync_prod_log_tailer(' in body, \
            '托管刷新未联动实时日志管线（管理器启动时生产已在跑的场景会没有输出）'
        sync = _func_src('log_view.py', '_sync_prod_log_tailer')
        assert 'ensure_started()' in sync and 'send' not in sync and '.stop()' in sync, \
            '管线开关必须在「在跑就接入 / 不在跑就收工」两个方向都成立'

    def test_startup_schedules_file_cleanup_and_init_runs(self):
        init = _func_src('app.py', '__init__')
        assert '_init_log_view()' in init, '日志缓冲未初始化（log_message 会 AttributeError）'
        assert '_schedule_log_file_cleanup()' in init, \
            '启动时未挂上日志文件定时清理 —— 文件又会只增不减'
        tick = _func_src('log_view.py', '_log_file_cleanup_tick')
        assert 'cleanup_log_files()' in tick and '_schedule_log_file_cleanup(' in tick, \
            '定时清理未形成「跑一轮 → 续一轮」的闭环（只会跑第一次）'

    def test_log_panel_exposes_cleanup_entry(self):
        text = (PKG / 'log_view.py').read_text(encoding='utf-8')
        assert '清理旧日志' in text, '日志面板没有手动清理入口'
        assert 'self.cleanup_log_files' in text, '入口未绑定到清理动作'
        assert '自动轮转+清理' in text, '面板未说明文件会被定时轮转与清理（用户会以为没人管）'
        assert 'rotate_oversized_logs' in text, '维护一轮没有接上轮转兜底'
        assert '_log_file_cleanup_tick' in text and 'cleanup_log_files' in text

    def test_policy_is_ui_configurable_and_shared(self):
        """策略不是代码常量：面板可改、落 config/log_policy.json，维护轮次每轮现读。"""
        panel = (PKG / 'log_view.py').read_text(encoding='utf-8')
        assert 'open_log_policy_dialog' in panel
        assert '设置' in panel, '面板没有策略设置入口'
        assert 'save_log_policy(' in panel and 'policy_from_fields(' in panel, \
            '设置对话框未接上「校验 + 持久化」'
        assert "'config'" in panel and 'log_policy.json' in panel, \
            '桌面壳必须显式拼策略路径（打包后 __file__ 指向解包临时目录）'
        cleanup = _func_src('log_view.py', 'cleanup_log_files')
        assert 'self._log_policy()' in cleanup, '维护轮次没有现读策略（改了设置要重启才生效）'

    def test_health_check_is_scheduled_and_dispatch_is_wired(self):
        init = _func_src('app.py', '__init__')
        assert '_schedule_log_health()' in init, '启动时未挂上日志巡检'
        dispatch = _func_src('app.py', '_process_pending_messages')
        assert "'log_health'" in dispatch and '_apply_log_health(' in dispatch, \
            '巡检结果没有回主线程的派发分支（面板永远不会更新）'
        tick = _func_src('log_view.py', '_log_health_tick')
        assert 'run_log_health_check()' in tick and '_schedule_log_health(' in tick, \
            '巡检未形成「跑一轮 → 续一轮」的闭环'
        panel = (PKG / 'log_view.py').read_text(encoding='utf-8')
        assert 'log_health_label' in panel and '巡检' in panel, '面板没有巡检行/入口'
        apply_body = _func_src('log_view.py', '_apply_log_health')
        assert 'log_health_label.configure' in apply_body, '巡检结果没渲染到面板行上'
        assert "'WARNING'" in apply_body, '异常增长未升级为告警日志'
        assert '_log_health_baselined' in apply_body, '缺少「首次增长率基线记一行」的落点'

    def test_quit_stops_tailer(self):
        body = _func_src('app.py', '_do_quit')
        assert 'prod_logs.stop()' in body, '退出未收掉回灌线程'

    def test_emergency_stop_stops_tailer(self):
        body = _func_src('app.py', 'stop_all')
        assert 'prod_logs.stop()' in body, '紧急停止后旧日志会继续往面板里刷'


class TestCleanupEntryPoint:
    def test_cleanup_log_files_reports_through_queue(self, tmp_path):
        """面板按钮的落点：真线程 + 真清理 + 总结回消息队列（不需要 Tk）。

        mixin 以 host 方式绑定，证明本层只依赖 ``_PROJECT_DIR`` / ``_msg_queue``
        两个契约（与 hosting_view 的 mixin 一致）。
        """
        (tmp_path / 'logs').mkdir()
        old = _write_log(tmp_path / 'logs' / 'server_manager_20260101.log', 10, 40, time.time())
        host = LogViewMixin()
        host._PROJECT_DIR = tmp_path
        host._msg_queue = queue.Queue()
        host.cleanup_log_files()
        for _ in range(100):
            if not host._msg_queue.empty():
                break
            time.sleep(0.05)
        texts = []
        while not host._msg_queue.empty():
            kind, data = host._msg_queue.get_nowait()
            assert kind == 'log'
            texts.append(data['text'])
        assert any('日志轮转兜底' in t for t in texts), '维护一轮必须先跑轮转兜底'
        assert any('删除 1 个文件' in t for t in texts), texts
        assert not old.exists()


class TestRotationFallback:
    """轮转兜底：管理器自己给「没人管」的日志止血，不再依赖 ARQ 的每日 cron。

    压力点在两个物理约束上：① 文件被 nginx/NSSM 长期打开，Windows 不让 rename，
    只能 copytruncate；② 绝不能去动 NSSM 自己按 10MB 轮转的服务日志。
    """

    def test_oversized_file_is_rotated_with_one_generation(self, tmp_path):
        log = tmp_path / 'nginx-error.log'
        log.write_bytes(b'E' * 4096)
        report = rotate_oversized_logs(tmp_path, max_bytes=1024)
        assert [p.name for p, _ in report.rotated] == ['nginx-error.log']
        assert log.stat().st_size == 0, '现行文件必须清零（持有方接着写尾）'
        assert (tmp_path / 'nginx-error.log.1').read_bytes() == b'E' * 4096
        assert '已轮转 1 个' in report.summary() and 'nginx-error.log' in report.summary()

    def test_files_below_threshold_are_left_alone(self, tmp_path):
        log = tmp_path / 'server_manager_20260930.log'
        log.write_bytes(b's' * 100)
        report = rotate_oversized_logs(tmp_path, max_bytes=1024)
        assert report.rotated == []
        assert log.stat().st_size == 100
        assert not (tmp_path / 'server_manager_20260930.log.1').exists()
        assert '无超限日志' in report.summary()

    def test_rotated_copies_are_never_rotated_again(self, tmp_path):
        """只轮转现行 ``*.log``：动副本会生出 .1.1 链，数量指数长。"""
        (tmp_path / 'nginx-error.log.1').write_bytes(b'x' * 4096)
        (tmp_path / 'erp.log.2026-09-29').write_bytes(b'x' * 4096)
        report = rotate_oversized_logs(tmp_path, max_bytes=1024)
        assert report.rotated == []
        assert (tmp_path / 'nginx-error.log.1').stat().st_size == 4096

    def test_nssm_service_logs_stay_under_the_fallback_threshold(self):
        """阈值必须高于 NSSM 的 AppRotateBytes(10MB)，否则会和 NSSM 抢同一个文件。"""
        assert LOG_ROTATE_BYTES >= 10 * 1024 * 1024 * 4

    def test_locked_file_is_reported_not_fatal(self, tmp_path):
        (tmp_path / 'nginx-access.log').write_bytes(b'x' * 4096)
        report = rotate_oversized_logs(tmp_path, max_bytes=1024, rotate=lambda p, m: False)
        assert report.rotated == [] and [p.name for p in report.skipped] == ['nginx-access.log']
        assert '被占用未能轮转' in report.summary()

    def test_copytruncate_tolerates_missing_and_locked_files(self, tmp_path):
        assert rotate_file_copytruncate(tmp_path / 'nope.log', 1) is False
        small = tmp_path / 'small.log'
        small.write_bytes(b'x')
        assert rotate_file_copytruncate(small, 1024) is False


class TestLogHealth:
    """巡检层：增长率必须来自两次采样，且「谁在疯长 / 总量爆了」都要报得出来。"""

    def test_first_sample_has_no_growth_and_no_alarm(self, tmp_path):
        """首轮没有基线 —— 绝不能拿「现有体积」当「增长」报警。"""
        _write_log(tmp_path / 'erp-prod.log', 5 * 1024 * 1024, 0, time.time())
        report = inspect_log_health(tmp_path, now=time.time())
        assert report.first_sample is True
        assert report.files[0].growth_bytes_per_day is None
        assert report.alerts() == []
        assert '两次采样' in report.summary()

    def test_growth_rate_from_two_samples(self, tmp_path):
        """第二轮相对第一轮的增量 ÷ 时间间隔 × 86400 —— 这就是「谁在疯长」的依据。"""
        now = time.time()
        log = tmp_path / 'erp-prod.log'
        _write_log(log, 1024 * 1024, 0, now)
        inspect_log_health(tmp_path, now=now)                    # 第一轮建基线
        _write_log(log, 1024 * 1024 + 20 * 1024 * 1024, 0, now)  # 涨了 20MB
        report = inspect_log_health(tmp_path, now=now + 3600)    # 隔 1 小时
        stat = report.files[0]
        assert report.first_sample is False
        assert stat.growth_bytes_per_day == pytest.approx(20 * 1024 * 1024 * 24, rel=0.01)
        assert '增长最快' in report.summary() and 'erp-prod.log' in report.summary()

    def test_idle_files_are_not_reported_as_growing(self, tmp_path):
        """安静时几乎所有文件都是 0 增长 —— 绝不能把 0.0MB/天 排进「增长最快」。"""
        now = time.time()
        for name in ('erp.log', 'error.log', 'fastapi_20260930.log'):
            _write_log(tmp_path / name, 1024 * 1024, 0, now)
        inspect_log_health(tmp_path, now=now)
        report = inspect_log_health(tmp_path, now=now + 3600)
        assert report.hottest() == []
        assert '本轮采样区间内无文件增长' in report.summary()
        assert report.alerts() == []

    def test_runaway_file_raises_alert_with_share(self, tmp_path):
        now = time.time()
        fast = tmp_path / 'error.log'
        quiet = tmp_path / 'access.log'
        _write_log(fast, 1024, 0, now)
        _write_log(quiet, 1024, 0, now)
        inspect_log_health(tmp_path, now=now)
        _write_log(fast, 1024 + LOG_ALERT_BYTES_PER_DAY, 0, now)
        report = inspect_log_health(tmp_path, now=now + 3600)
        names = [f.name for f in report.warn_files()]
        assert names == ['error.log'], '只有疯长的那个该被告警'
        assert report.hottest(1)[0].name == 'error.log'
        assert 99 < report.share_of(report.files[0]) <= 100
        assert any('日志异常增长' in m and 'error.log' in m for m in report.alerts())

    def test_second_sample_too_close_is_ignored(self, tmp_path):
        """间隔太短会把噪声放大成天文数字 —— 这一轮宁可不给数字。"""
        now = time.time()
        log = tmp_path / 'erp-prod.log'
        _write_log(log, 1024, 0, now)
        inspect_log_health(tmp_path, now=now)
        _write_log(log, 4096, 0, now)
        report = inspect_log_health(tmp_path, now=now + 5)
        assert report.files[0].growth_bytes_per_day is None
        assert report.alerts() == []

    def test_over_cap_raises_alert(self, tmp_path):
        now = time.time()
        _write_log(tmp_path / 'erp-prod.log', 1024, 0, now)
        inspect_log_health(tmp_path, max_total_bytes=10 ** 9, now=now)
        report = inspect_log_health(tmp_path, max_total_bytes=512, now=now + 3600)
        assert report.over_cap is True
        assert any('已超保留上限' in m for m in report.alerts())

    def test_state_snapshot_is_not_treated_as_a_log(self, tmp_path):
        """状态快照自己不能被统计进去、也不能被清理掉（否则基线每轮都丢）。"""
        now = time.time()
        _write_log(tmp_path / 'erp-prod.log', 1024, 40, now)
        inspect_log_health(tmp_path, now=now)
        state = tmp_path / LOG_HEALTH_STATE_NAME
        assert state.exists()
        report = inspect_log_health(tmp_path, now=now + 3600)
        assert LOG_HEALTH_STATE_NAME not in [f.name for f in report.files]
        pruned = prune_log_files(tmp_path, keep_days=14, now=now)
        # 过期日志该被删（用例非空转），但状态快照不在候选里、必须活下来
        assert [p.name for p in pruned.deleted] == ['erp-prod.log']
        assert state.exists(), '状态快照被当做日志删掉了（基线每轮都会丢）'

    def test_missing_dir_is_an_empty_report(self, tmp_path):
        report = inspect_log_health(tmp_path / 'nope', now=time.time())
        assert report.files == [] and report.total_bytes == 0
        assert '合计 0.0MB' in report.summary()
        assert isinstance(report, LogHealthReport)


class TestPruneLogFiles:
    def test_expired_deleted_fresh_kept(self, tmp_path):
        now = time.time()
        old = _write_log(tmp_path / 'server_manager_20260101.log', 10, 20, now)
        fresh = _write_log(tmp_path / 'erp-prod.log', 10, 0, now)
        report = prune_log_files(tmp_path, keep_days=14, now=now)
        assert old in report.deleted
        assert not old.exists()
        assert fresh.exists()
        assert fresh not in report.deleted
        assert report.kept == 1
        assert '删除 1 个文件' in report.summary()

    def test_state_files_are_never_touched(self, tmp_path):
        """状态文件不是日志：``prod_runner.json``/``nginx.pid`` 删了会打断就绪判定。"""
        now = time.time()
        keepers = [_write_log(tmp_path / name, 10, 60, now)
                   for name in ('prod_runner.json', 'nginx.pid', 'watchdog_state.json')]
        report = prune_log_files(tmp_path, keep_days=14, now=now)
        assert report.deleted == []
        for path in keepers:
            assert path.exists()
        assert report.kept == 0

    def test_size_cap_deletes_oldest_first(self, tmp_path):
        now = time.time()
        oldest = _write_log(tmp_path / 'a.log', 100, 30, now)
        middle = _write_log(tmp_path / 'b.log', 100, 20, now)
        newest = _write_log(tmp_path / 'c.log', 100, 10, now)
        report = prune_log_files(tmp_path, keep_days=365, max_total_bytes=150, now=now)
        assert report.deleted == [oldest, middle]
        assert newest.exists()
        assert report.kept == 1

    def test_activity_cap_protects_being_written_file(self, tmp_path):
        """正在写的日志（1 小时内有写入）即使超上限也不删 —— 免得清掉生产在用的日志。"""
        now = time.time()
        active = _write_log(tmp_path / 'erp-prod.log', 4096, 0, now)
        report = prune_log_files(tmp_path, keep_days=14, max_total_bytes=1, now=now)
        assert report.deleted == []
        assert active.exists()
        assert report.kept == 1

    def test_locked_file_is_reported_not_fatal(self, tmp_path):
        """被占用删不掉的文件只记 skipped，不能让整轮清理崩掉（NSSM 正在写）。"""
        now = time.time()
        locked = _write_log(tmp_path / 'erp-arq.log', 10, 30, now)

        def _deny(path):
            raise PermissionError(32, '另一个程序正在使用此文件')

        report = prune_log_files(tmp_path, keep_days=14, now=now, remove=_deny)
        assert report.deleted == []
        assert report.skipped == [locked]
        assert locked.exists()
        assert '被占用跳过' in report.summary()

    def test_missing_dir_is_empty_report(self, tmp_path):
        report = prune_log_files(tmp_path / 'nope', now=time.time())
        assert report.deleted == [] and report.skipped == [] and report.kept == 0
        assert '无过期文件' in report.summary()
