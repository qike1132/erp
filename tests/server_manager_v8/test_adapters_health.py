"""健康探测适配器测试：真实本地 HTTP 服务 + 关闭端口失败路径 + Redis PING。"""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from server_manager_v8.adapters.health_http import HttpHealthAdapter, redis_ping
from server_manager_v8.domain import FailureTracker, HealthTarget


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == '/api/health':
            self.send_response(200)
            self.send_header('Content-Length', '2')
            self.end_headers()
            self.wfile.write(b'ok')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args) -> None:
        return


@pytest.fixture()
def http_server():
    server = HTTPServer(('127.0.0.1', 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()


class TestProbeHttp:
    def test_healthy(self, http_server) -> None:
        target = HealthTarget(
            name='api', kind='http', port=http_server.server_address[1],
            path='/api/health', timeout_s=2.0,
        )
        sample = HttpHealthAdapter().probe(target)
        assert sample.ok and sample.status_code == 200
        assert sample.latency_ms >= 0

    def test_not_found_is_unhealthy(self, http_server) -> None:
        target = HealthTarget(
            name='api', kind='http', port=http_server.server_address[1],
            path='/nope', timeout_s=2.0,
        )
        assert not HttpHealthAdapter().probe(target).ok

    def test_closed_port_unhealthy_with_error(self) -> None:
        target = HealthTarget(name='x', kind='http', port=1, timeout_s=1.0)
        sample = HttpHealthAdapter().probe(target)
        assert not sample.ok and sample.error

    def test_probe_until_ready_immediate(self, http_server) -> None:
        target = HealthTarget(
            name='api', kind='http', port=http_server.server_address[1], path='/api/health',
        )
        sample = HttpHealthAdapter().probe_until_ready(target, timeout_s=5.0)
        assert sample.ok

    def test_probe_until_ready_times_out(self) -> None:
        target = HealthTarget(name='x', kind='http', port=1, timeout_s=0.5)
        sample = HttpHealthAdapter().probe_until_ready(target, timeout_s=2.0)
        assert not sample.ok


class TestProbeTcp:
    def test_open_port(self, http_server) -> None:
        target = HealthTarget(
            name='redis', kind='tcp', port=http_server.server_address[1], timeout_s=2.0,
        )
        assert HttpHealthAdapter().probe(target).ok

    def test_closed_port(self) -> None:
        target = HealthTarget(name='redis', kind='tcp', port=1, timeout_s=1.0)
        assert not HttpHealthAdapter().probe(target).ok


class TestRedisPing:
    def test_closed_port_reports_error(self) -> None:
        sample = redis_ping(port=1, timeout_s=1.0)
        assert not sample.ok and sample.error

    def test_invalid_resp_is_unhealthy(self) -> None:
        """对普通 TCP 服务发 RESP PING → 非 PONG 响应 → 不健康。"""
        probe = __import__('socket').socket()
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
        probe.listen(1)
        thread = threading.Thread(
            target=lambda: probe.accept(), daemon=True,
        )
        thread.start()
        sample = redis_ping(port=port, timeout_s=2.0)
        probe.close()
        assert not sample.ok


class TestFailureTrackerIntegration:
    def test_consecutive_failures_flip_health(self, http_server) -> None:
        """探针 + FailureTracker：连续失败 3 次才判不健康（防抖链路完整）。"""
        tracker = FailureTracker(threshold=3, startup_grace_s=0)
        adapter = HttpHealthAdapter()
        target = HealthTarget(name='api', kind='http', port=1, timeout_s=0.5)
        for ts in (1.0, 2.0, 3.0):
            sample = adapter.probe(target)
            assert not sample.ok  # 关闭端口必然失败
            tracker.record(sample.ok, ts=ts)  # ok=False → 记为失败
        assert tracker.consecutive_fail == 3
        assert tracker.is_down()
        ok_target = HealthTarget(
            name='api', kind='http', port=http_server.server_address[1], path='/api/health',
        )
        ok_sample = adapter.probe(ok_target)
        assert ok_sample.ok
        tracker.record(ok_sample.ok, ts=4.0)
        assert not tracker.is_down() and tracker.consecutive_fail == 0
