"""`adapters.health_http` 的测试。

★ 最重要的断言是 **`test_clears_all_proxies`** ——
它守的是一个已定位的真实事故（2026-09-10）：

    本机有 HTTP_PROXY/HTTPS_PROXY=127.0.0.1:57562 且无 NO_PROXY，
    urllib 默认读系统代理（含 Windows 注册表），把探测 127.0.0.1:5002 的请求
    路由进代理。代理客户端抖动 → 健康检查间歇失败 → prod_runner 触发
    「连续失败 20s → 强制重启」的**后端重启风暴**，而应用完全正常。

若这条测试失败，意味着探针可能重新走代理，事故会复发。
"""

from __future__ import annotations

import urllib.request
from types import SimpleNamespace

import pytest

from server_manager_v8.adapters import health_http as H


class TestBuildDirectOpener:
    """★ 这一组测试守的是一个已定位的真实事故（2026-09-10）。

    机制（**实测确认，别按直觉想当然**）：

      `urllib.request.build_opener(ProxyHandler({}))` 之后，
      opener 的 handlers 里**根本没有** ProxyHandler —— 因为 build_opener
      会把「没添加任何新能力」的 handler 去重掉（ProxyHandler({}) 的 proxies
      为空，被判定为无贡献）。

      而默认的 `build_opener()`（不传参数）会**自动补一个**
      `ProxyHandler(getproxies())`，proxies 里带着环境/注册表代理。

      `urllib` 在找不到 ProxyHandler 时，`_proxy_open` 返回 None（不走代理）；
      找到时才会拿 proxies 去匹配 —— 这就是「有没有那个 handler」决定一切的原理。

      所以「修好了」的**表现是 handlers 里没有 ProxyHandler**，
      而不是「有一个 proxies 为空的 handler」。

    下面 `test_env_proxy_would_be_used_without_the_fix` 用一个反例锁住这个理解：
    默认 opener 在有代理环境变量时**必然**带上代理配置。
    """

    def test_no_proxy_handler_means_direct_connection(self):
        """★ 核心断言：直连 opener 的 handlers 中**不应存在** ProxyHandler。

        存在即意味着请求可能被路由进代理 → 事故复发。
        """
        opener = H.build_direct_opener()
        proxy_handlers = [
            h for h in opener.handlers
            if isinstance(h, urllib.request.ProxyHandler)
        ]
        assert proxy_handlers == [], (
            f'直连 opener 不该有 ProxyHandler，实际: '
            f'{[h.proxies for h in proxy_handlers]}'
        )

    def test_env_proxy_would_be_used_without_the_fix(self, monkeypatch):
        """反例：不传 ProxyHandler({}) 时，环境代理**会被采纳**。

        这条测试的存在是为了证明上一条测试有意义 ——
        如果两者行为一样，那 build_direct_opener 就是个空操作。
        """
        monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:57562')
        monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:57562')
        naive = urllib.request.build_opener()
        proxy_handlers = [
            h for h in naive.handlers
            if isinstance(h, urllib.request.ProxyHandler)
        ]
        assert proxy_handlers, '默认 opener 在有代理环境下必须带 ProxyHandler'
        assert proxy_handlers[0].proxies != {}, (
            '默认 opener 的代理配置不应为空 —— 否则本反例失去意义'
        )

    def test_direct_opener_differs_from_naive_when_proxy_set(self, monkeypatch):
        """★ 直接对比：有代理环境时，两者必须不同。"""
        monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:57562')

        def proxy_count(opener):
            return len([h for h in opener.handlers
                        if isinstance(h, urllib.request.ProxyHandler)])

        assert proxy_count(urllib.request.build_opener()) == 1
        assert proxy_count(H.build_direct_opener()) == 0

    def test_returns_opener_with_open(self):
        opener = H.build_direct_opener()
        assert callable(getattr(opener, 'open', None))

    def test_opener_still_has_standard_handlers(self):
        """清空代理不该把其它能力一并清掉（HTTP/HTTPS/重定向仍需可用）。"""
        opener = H.build_direct_opener()
        names = {type(h).__name__ for h in opener.handlers}
        assert 'HTTPHandler' in names
        assert 'HTTPSHandler' in names


class TestHealthSample:
    def test_failure_without_detail_rejected(self):
        with pytest.raises(ValueError, match='detail'):
            H.HealthSample(ok=False)

    def test_success_needs_no_detail(self):
        assert H.HealthSample(ok=True).detail == ''

    def test_frozen(self):
        s = H.HealthSample(ok=True)
        with pytest.raises(Exception):
            s.ok = False


class FakeResponse:
    def __init__(self, status=200, raises_on_close=False, raises_on_status=False):
        self.status = status
        self._raises_on_close = raises_on_close
        self._raises_on_status = raises_on_status

    def close(self):
        if self._raises_on_close:
            raise RuntimeError('close failed')


class FakeOpener:
    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.calls = []

    def open(self, url, timeout=None):
        self.calls.append((url, timeout))
        if self.exc:
            raise self.exc
        return self.response


class TestProbe:
    def test_ok_when_response_returned(self):
        op = FakeOpener(FakeResponse())
        assert H.probe('http://127.0.0.1:5002/api/health', opener=op).ok is True

    def test_records_latency(self):
        ticks = iter([100.0, 100.25])

        def clock():
            return next(ticks)

        op = FakeOpener(FakeResponse())
        s = H.probe('http://x', opener=op, clock=clock)
        assert s.latency_ms == pytest.approx(250.0)

    def test_captures_status_code(self):
        op = FakeOpener(FakeResponse(status=204))
        assert H.probe('http://x', opener=op).status_code == 204

    def test_failure_records_detail(self):
        op = FakeOpener(exc=ConnectionRefusedError('refused'))
        s = H.probe('http://x', opener=op)
        assert s.ok is False
        assert 'ConnectionRefusedError' in s.detail
        assert 'refused' in s.detail

    def test_timeout_failure_is_not_ok(self):
        op = FakeOpener(exc=TimeoutError('timed out'))
        s = H.probe('http://x', opener=op)
        assert s.ok is False
        assert 'TimeoutError' in s.detail

    def test_never_raises(self):
        """★ 单次失败不冒泡 —— 调用方（wait_until 循环）靠重复探测 + 超时处理。"""
        for exc in (OSError('x'), ValueError('y'), RuntimeError('z')):
            assert H.probe('http://x', opener=FakeOpener(exc=exc)).ok is False

    def test_5xx_still_counts_as_ok(self):
        """★ 语义保真：旧实现「拿到响应即通过」，**不检查状态码**。

        探针的目的是「端口是否在响应」，不是「业务是否健康」
        （后者由 prod_runner 自身的健康检查负责）。
        改动它会让启动就绪判定变严，可能引入「明明起来了却判失败」的新故障。
        """
        op = FakeOpener(FakeResponse(status=500))
        s = H.probe('http://x', opener=op)
        assert s.ok is True
        assert s.status_code == 500

    def test_404_still_counts_as_ok(self):
        op = FakeOpener(FakeResponse(status=404))
        assert H.probe('http://x', opener=op).ok is True

    def test_uses_default_timeout_of_2(self):
        """迁移自 `_probe_http(url, timeout=2)`。"""
        op = FakeOpener(FakeResponse())
        H.probe('http://x', opener=op)
        assert op.calls == [('http://x', 2.0)]

    def test_custom_timeout_forwarded(self):
        op = FakeOpener(FakeResponse())
        H.probe('http://x', opener=op, timeout=7)
        assert op.calls == [('http://x', 7)]

    def test_response_closed_on_success(self):
        """补上的资源管理：旧实现没有显式 close，会泄漏连接。"""
        resp = FakeResponse()
        closed = []
        resp.close = lambda: closed.append(True)
        H.probe('http://x', opener=FakeOpener(resp))
        assert closed == [True]

    def test_close_failure_does_not_break_result(self):
        """close 抛异常不该影响已决定的 ok。"""
        op = FakeOpener(FakeResponse(raises_on_close=True))
        assert H.probe('http://x', opener=op).ok is True

    def test_url_passed_through_unchanged(self):
        op = FakeOpener(FakeResponse())
        H.probe('http://127.0.0.1:3000/nginx-health', opener=op)
        assert op.calls[0][0] == 'http://127.0.0.1:3000/nginx-health'


class TestMakeProbeFn:
    def test_returns_bool_predicate(self, monkeypatch):
        """domain.wait_until 的 predicate 需要 `() -> bool` 形状。"""
        monkeypatch.setattr(H, 'probe', lambda url, **kw: H.HealthSample(ok=True))
        fn = H.make_probe_fn()
        assert fn('http://x') is True

    def test_returns_false_on_failure(self, monkeypatch):
        monkeypatch.setattr(
            H, 'probe',
            lambda url, **kw: H.HealthSample(ok=False, detail='down'),
        )
        assert H.make_probe_fn()('http://x') is False

    def test_kwargs_forwarded(self, monkeypatch):
        seen = {}

        def fake_probe(url, **kw):
            seen['url'] = url
            seen['kw'] = kw
            return H.HealthSample(ok=True)

        monkeypatch.setattr(H, 'probe', fake_probe)
        H.make_probe_fn(timeout=9)('http://x')
        assert seen == {'url': 'http://x', 'kw': {'timeout': 9}}

    def test_usable_as_wait_predicate(self, monkeypatch):
        """端到端：与 domain.readiness.wait_until 组合可用。

        这是适配层存在的意义 —— 领域层定义形状，适配层提供实现。
        """
        from server_manager_v8.domain.readiness import (
            WaitPolicy,
            WaitStatus,
            wait_until,
        )

        state = {'calls': 0}

        def fake_probe(url, **kw):
            state['calls'] += 1
            if state['calls'] >= 3:
                return H.HealthSample(ok=True)
            return H.HealthSample(ok=False, detail='not ready yet')

        monkeypatch.setattr(H, 'probe', fake_probe)

        fake_time = {'t': 0.0}

        def clock():
            return fake_time['t']

        def sleep(s):
            fake_time['t'] += s

        fn = H.make_probe_fn()
        outcome = wait_until(
            lambda: fn('http://x'),
            WaitPolicy(timeout_s=30, interval_s=1),
            clock=clock,
            sleep=sleep,
        )
        assert outcome.status is WaitStatus.SATISFIED
        assert outcome.attempts == 3

    def test_usable_with_named_policy_constant(self, monkeypatch):
        """与真实策略常量组合 —— 确认形状兼容，不依赖自造的 WaitPolicy。"""
        from server_manager_v8.domain.readiness import (
            POLICY_HTTP_BACKEND,
            WaitStatus,
            wait_until,
        )

        state = {'calls': 0}

        def fake_probe(url, **kw):
            state['calls'] += 1
            if state['calls'] >= 2:
                return H.HealthSample(ok=True)
            return H.HealthSample(ok=False, detail='starting')

        monkeypatch.setattr(H, 'probe', fake_probe)
        fake_time = {'t': 0.0}
        fn = H.make_probe_fn()
        outcome = wait_until(
            lambda: fn('http://x'),
            POLICY_HTTP_BACKEND,
            clock=lambda: fake_time['t'],
            sleep=lambda s: fake_time.__setitem__('t', fake_time['t'] + s),
        )
        assert outcome.status is WaitStatus.SATISFIED
        assert outcome.attempts == 2
