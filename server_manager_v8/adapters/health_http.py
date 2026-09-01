"""健康探测适配器 — 实现 domain.ports.HealthPort。

迁移来源（server_manager.py v6）：启动流程中 urllib 轮询 /api/health 与
Redis RESP PING。升级为 K8s 三类探针语义（startup/liveness/readiness），
复用 domain.health.FailureTracker 做连续失败防抖。

http 探针：GET 目标路径，2xx/3xx 视为健康（v6 语义），记录 latency_ms。
tcp 探针：连接成功即健康（liveness 语义）。
"""

from __future__ import annotations

import socket
import time
import urllib.error
import urllib.request

from server_manager_v8.domain import (
    HealthSample,
    HealthTarget,
)

__all__ = ['HttpHealthAdapter', 'redis_ping']


class HttpHealthAdapter:
    """HTTP / TCP / Redis 健康探测。按目标类型分派。"""

    def probe(self, target: HealthTarget) -> HealthSample:
        if target.kind == 'tcp':
            return self._probe_tcp(target)
        if target.kind == 'redis':
            return redis_ping(target.port, target.password, target.timeout_s)
        return self._probe_http(target)

    def probe_until_ready(self, target: HealthTarget, timeout_s: float) -> HealthSample:
        """轮询探测直到成功或超时（startup/readiness 语义）。"""
        deadline = time.monotonic() + timeout_s
        last = self.probe(target)
        while not last.ok and time.monotonic() < deadline:
            time.sleep(1)
            last = self.probe(target)
        return last

    # ---- 内部 ----

    @staticmethod
    def _probe_http(target: HealthTarget) -> HealthSample:
        url = f'http://127.0.0.1:{target.port}{target.path or "/"}'
        start = time.monotonic()
        try:
            with urllib.request.urlopen(url, timeout=target.timeout_s) as resp:
                latency = int((time.monotonic() - start) * 1000)
                status = resp.status
                ok = 200 <= status < 400
                return HealthSample(ok=ok, latency_ms=latency, status_code=status)
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            latency = int((time.monotonic() - start) * 1000)
            return HealthSample(ok=False, latency_ms=latency, error=str(exc))

    @staticmethod
    def _probe_tcp(target: HealthTarget) -> HealthSample:
        start = time.monotonic()
        try:
            with socket.create_connection(('127.0.0.1', target.port), timeout=target.timeout_s):
                latency = int((time.monotonic() - start) * 1000)
                return HealthSample(ok=True, latency_ms=latency)
        except OSError as exc:
            latency = int((time.monotonic() - start) * 1000)
            return HealthSample(ok=False, latency_ms=latency, error=str(exc))


def redis_ping(port: int, password: str = '', timeout_s: float = 1.0) -> HealthSample:
    """Redis 可用性探测（v6 _is_redis_running 迁移）。

    语义（勿简化）：仅端口探测会误报 —— Redis Paused/停止或密码不匹配时
    端口探测仍可能通过。必须 RESP PING：+PONG 可用；-NOAUTH 先 AUTH 再 PING。
    """
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=timeout_s) as sock:
            sock.sendall(b'*1\r\n$4\r\nPING\r\n')
            resp = sock.recv(64)
            if resp.startswith(b'+PONG'):
                return HealthSample(ok=True, latency_ms=1, status_code=200)
            if resp.startswith(b'-NOAUTH'):
                if not password:
                    return HealthSample(ok=False, error='Redis 需要认证但未提供密码')
                auth_cmd = f'*2\r\n$4\r\nAUTH\r\n${len(password)}\r\n{password}\r\n'.encode()
                sock.sendall(auth_cmd)
                auth_resp = sock.recv(64)
                if not auth_resp.startswith(b'+OK'):
                    return HealthSample(ok=False, error='Redis 认证失败（密码错误）')
                sock.sendall(b'*1\r\n$4\r\nPING\r\n')
                ok = sock.recv(64).startswith(b'+PONG')
                return HealthSample(ok=ok, error='' if ok else 'Redis 认证后 PING 仍失败')
            return HealthSample(ok=False, error=f'意外响应: {resp[:32]!r}')
    except OSError as exc:
        return HealthSample(ok=False, error=str(exc))
