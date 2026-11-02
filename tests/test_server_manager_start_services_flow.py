"""server_manager「启动生产服务」流程的回归测试（2026-10-16）。

背景：4169aa03 删「零引用 Redis 转发」时，把**仍有调用点**的 `_start_redis`
一并删掉了，但 `_start_services_flow` 里的 `self._start_redis()` 没跟着改。
于是用户在管理器上点「启动服务」（本机恢复生产的唯一入口）时：界面先打出
「正在启动生产模式 → 已自动停止开发模式 → 正在清理端口」（旧状态已被摧毁），
随后 AttributeError 被 ActionGate 转成一行「执行异常」，**五个服务一个都不会
被 start** —— 唯一的生产启动通道不可用，且失败方式是「先毁旧、再静默不建新」。

为什么旧测试没抓到：tests/test_server_manager_stop_scope.py:52 的
`assert "_start_redis()" in body` 是**文本断言**，源码里确实有这串字符
（在被删转发的调用点处），所以常绿。本文件改为**行为断言**：真的执行流程，
断言 Redis 启动被调用到且不抛 AttributeError。

运行: python -m pytest tests/test_server_manager_start_services_flow.py -q
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server_manager.app as sm


def _make_app():
    """绕过 Tk 构造（__init__ 会触碰 self.root），仅取无状态逻辑。"""
    return object.__new__(sm.ServerManagerApp)


@pytest.mark.skipif(sys.platform != "win32", reason="server_manager 仅 Windows 可跑")
class TestStartServicesFlow:
    """_start_services_flow 必须真的走到 Redis 启动，而不是 AttributeError。"""

    def test_start_redis_forwarding_exists(self):
        """`_start_redis` 转发必须在 app 上可解析（这是删转发时漏掉的那个）。"""
        app = _make_app()
        assert hasattr(app, '_start_redis'), (
            '`_start_redis` 转发缺失 —— `_start_services_flow` 调用它会 AttributeError，'
            '「启动生产服务」整条流程在 Redis 那步崩死，五个服务都不会被 start'
        )

    def test_start_services_flow_reaches_redis_start(self, monkeypatch):
        """真的跑一遍 _start_services_flow，断言 Redis 启动被调用到。

        M11（2026-10-26 上线前检查）：原测试名叫「flow」，实际只调了
        `app._start_redis()` —— 流程入口 `_start_services_flow()` 一次都没执行。
        删掉 `_start_services_flow` 里的 `self._start_redis()` 调用（或删掉转发本身），
        该测试仍然全绿，正是线上那次事故的形状。现在桩掉流程里的所有副作用，
        真正进入流程体。
        """
        app, hooks = _wire_flow_app(monkeypatch)

        app._start_services_flow()

        assert hooks['redis_started'] == 1, '启动流程必须调用 Redis 启动'
        assert hooks['start_one'] == 3, (
            f'三个服务都必须被启动，实际 {hooks["start_one"]} 次')
        assert hooks['logs_started'] == 1, '启动后必须拉起日志跟踪器'
        texts = _texts(app)
        assert any('生产模式启动完成' in t for t in texts), texts

    def test_flow_survives_redis_returning_false(self, monkeypatch):
        """Redis 启动失败只应告警，不能让整条启动流程崩掉（服务仍要起）。"""
        app, hooks = _wire_flow_app(monkeypatch, redis_ok=False)

        app._start_services_flow()

        assert hooks['redis_started'] == 1
        assert hooks['start_one'] == 3, 'Redis 失败也必须继续启动三个服务'
        texts = _texts(app)
        assert any('Redis 未启动' in t and '警告' in t for t in texts), texts

    def test_flow_reports_incomplete_when_arq_broker_missing(self, monkeypatch):
        """broker 未就绪：ARQ 不得计入成功，最终结论必须是「未完全成功」。"""
        app, hooks = _wire_flow_app(monkeypatch, broker_ok=False)

        app._start_services_flow()

        texts = _texts(app)
        assert any('未完全成功' in t for t in texts), texts
        assert not any('生产模式启动完成' in t for t in texts), texts
        assert hooks['start_one'] == 3, '仍要尝试启动 ARQ，让日志自己说话'

    def test_flow_refuses_before_any_side_effect_on_branch_denial(self, monkeypatch):
        """AUD-28：分支闸门拒绝时，不得停开发、不得清端口、不得启动任何服务。"""
        app, hooks = _wire_flow_app(monkeypatch)
        monkeypatch.setattr(sm.git_guard, 'check_production_branch',
                            lambda _root: (False, '工作区不在 main 分支'))

        app._start_services_flow()

        assert hooks == {
            'redis_started': 0, 'start_one': 0, 'logs_started': 0,
            'dev_stopped': 0, 'release_ports': 0,
        }, f'闸门拒绝后仍有副作用: {hooks}'
        assert any('拒绝启动' in t for t in _texts(app)), _texts(app)

    def test_flow_aborts_when_port_release_fails(self, monkeypatch):
        """2026-10-26：端口没清干净必须中止启动。

        继续启动只会得到一个「绑上了端口但收不到流量」的新实例（Windows SO_REUSEADDR
        允许两个 LISTEN，旧进程继续 accept），界面上一切正常、线上跑的还是旧代码。
        """
        app, hooks = _wire_flow_app(monkeypatch)
        app._release_ports = lambda *a, **k: False

        app._start_services_flow()

        assert hooks['start_one'] == 0, '端口未清干净时不得启动任何服务'
        assert hooks['redis_started'] == 0
        texts = _texts(app)
        assert any('中止启动' in t for t in texts), texts


def _wire_flow_app(monkeypatch, *, redis_ok=True, broker_ok=True):
    """构造一个只跑逻辑的 ServerManagerApp，并记录流程中的关键副作用。"""
    app = _make_app()
    hooks = {
        'redis_started': 0, 'start_one': 0, 'logs_started': 0,
        'dev_stopped': 0, 'release_ports': 0,
    }

    app._msg_queue = _FakeQueue()
    app._gate = _Gate()
    app._prod_start_ts = 0.0
    # prod_logs 是 log_view 的只读 property（懒建 ProdLogTailer），只能替换底层实例
    app._prod_logs = SimpleNamespace(
        ensure_started=lambda: hooks.__setitem__('logs_started', hooks['logs_started'] + 1))
    app.log_message = lambda *a, **k: None
    app._ensure_development_stopped = (
        lambda *a, **k: hooks.__setitem__('dev_stopped', hooks['dev_stopped'] + 1) or True)
    app._release_ports = (
        # 2026-10-26：_release_ports 改为返回 bool（False = 端口没清干净，流程必须中止）。
        # 替身要按新契约返回 True，否则每个用例都会走"中止"分支。
        lambda *a, **k: hooks.__setitem__('release_ports', hooks['release_ports'] + 1) or True)
    app._ensure_redis_broker = lambda *a, **k: broker_ok

    class _FakeRedis:
        def start_redis(self):
            hooks['redis_started'] += 1
            return redis_ok

        def ensure_redis_broker(self):
            return broker_ok

    app.redis = _FakeRedis()

    def _start_one(name, timeout=25):
        hooks['start_one'] += 1
        return SimpleNamespace(ok=True, state='4 RUNNING', pid=1000 + hooks['start_one'],
                               effective=True)

    app._start_one_service = _start_one

    monkeypatch.setattr(sm.git_guard, 'check_production_branch', lambda _root: (True, 'ok'))
    monkeypatch.setattr(sm.log_ops, 'log_file_size', lambda _p: 0)
    monkeypatch.setattr(sm.log_ops, 'read_log_tail_lines', lambda _p, **_k: [])
    return app, hooks


def _texts(app) -> list[str]:
    return [payload.get('text', '') for kind, payload in app._msg_queue.items
            if kind == 'log' and isinstance(payload, dict)]


class _Gate:
    def checkpoint(self):
        pass


class _FakeQueue:
    """够用的队列替身：只记录投递。"""

    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)

    def get(self, *a, **k):
        return self.items.pop(0) if self.items else None

    def get_nowait(self):
        return self.get()
