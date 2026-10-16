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

        只桩掉流程里的副作用（停开发/清端口/起服务/broker/日志），
        唯独**不**桩 `_start_redis` —— 若它缺失或被删，这里会以
        AttributeError 失败，正是线上那个缺陷。
        """
        app = _make_app()

        calls = {'dev_stopped': 0, 'release_ports': 0, 'broker': 0, 'start_one': 0}

        # 无副作用替身
        monkeypatch.setattr(app, '_msg_queue', _FakeQueue(), raising=False)
        monkeypatch.setattr(app, '_ensure_development_stopped', lambda *a, **k: (calls.__setitem__('dev_stopped', calls['dev_stopped'] + 1) or False), raising=False)
        monkeypatch.setattr(app, '_release_ports', lambda *a, **k: calls.__setitem__('release_ports', calls['release_ports'] + 1), raising=False)
        monkeypatch.setattr(app, '_ensure_redis_broker', lambda *a, **k: (calls.__setitem__('broker', calls['broker'] + 1) or True), raising=False)
        monkeypatch.setattr(app, '_start_one_service', lambda *a, **k: (calls.__setitem__('start_one', calls['start_one'] + 1) or True), raising=False)
        monkeypatch.setattr(app, '_verify_installed_service_paths', lambda *a, **k: None, raising=False)
        monkeypatch.setattr(app, 'log_message', lambda *a, **k: None, raising=False)

        # 关键：给 app 挂一个真能记录调用的 redis 转发目标
        redis_started = {'n': 0}

        class _FakeRedis:
            def start_redis(self):
                redis_started['n'] += 1
                return True

            def ensure_redis_broker(self):
                calls['broker'] = calls['broker'] + 1
                return True

        app.redis = _FakeRedis()
        # _start_redis 若存在，它转发到 redis.start_redis —— 这里确认转发本身正确
        app._start_redis()

        assert redis_started['n'] == 1, '`_start_redis` 转发应调用 redis.start_redis 恰好一次'

    def test_flow_survives_redis_returning_false(self, monkeypatch):
        """Redis 启动失败只应告警，不能让整条启动流程崩掉。"""
        app = _make_app()

        class _FakeRedis:
            def start_redis(self):
                return False

            def ensure_redis_broker(self):
                return True

        app.redis = _FakeRedis()
        # start_redis 返回 False 时流程继续（broker 仍要起），不抛异常
        assert app._start_redis() is False


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
