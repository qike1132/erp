"""症状化告警引擎测试：防抖求值、抑制、静默、冷却收敛、MTTA/MTTR、容量上限。"""
from __future__ import annotations

from server_manager_v8.domain import (
    Alert,
    AlertCenter,
    AlertRule,
    Inhibition,
    RuleEvaluator,
    Severity,
    Silence,
    SilenceBook,
)


def _rule(rid: str = 'api_health_fail', severity: Severity = Severity.P1,
          for_s: float = 30.0, service: str = 'api') -> AlertRule:
    return AlertRule(
        id=rid, metric='health_fail', op='ge', threshold=3,
        severity=severity, for_s=for_s, service=service,
        family='availability', runbook='docs/runbook/api_down.md', suggested_action='restart_api',
    )


class TestValidation:
    def test_p1_requires_runbook_and_action(self) -> None:
        no_runbook = AlertRule(id='x', metric='m', op='ge', threshold=1, severity=Severity.P1)
        no_action = AlertRule(id='x', metric='m', op='ge', threshold=1, severity=Severity.P1,
                              runbook='r.md')
        assert not no_runbook.validate().ok
        assert not no_action.validate().ok

    def test_p3_exempt_from_runbook(self) -> None:
        """P3 提示级豁免（CPU/内存/磁盘饱和度预警不强制 runbook）。"""
        r = AlertRule(id='sat', metric='cpu', op='ge', threshold=85, severity=Severity.P3)
        assert r.validate().ok

    def test_unknown_op_rejected(self) -> None:
        r = AlertRule(id='x', metric='m', op='~=', threshold=1, severity=Severity.P3)
        assert not r.validate().ok

    def test_evaluator_rejects_invalid_rules(self) -> None:
        import pytest
        with pytest.raises(ValueError, match='校验不通过'):
            RuleEvaluator([AlertRule(id='bad', metric='m', op='zz', threshold=1,
                                     severity=Severity.P1)])


class TestRuleEvaluator:
    def test_fire_only_after_for_window(self) -> None:
        """条件持续 30s 才触发；期间毛刺重置计时。"""
        ev = RuleEvaluator([_rule(for_s=30.0)])
        assert ev.feed('api', 'health_fail', 5, ts=0.0) == []  # 首次越界，未满窗
        assert ev.feed('api', 'health_fail', 5, ts=10.0) == []
        assert ev.feed('api', 'health_fail', 5, ts=20.0) == []
        fired = ev.feed('api', 'health_fail', 5, ts=30.0)  # 恰好 30s
        assert len(fired) == 1
        # 服务级规则的 key 即规则 ID（全局规则才带 @service 后缀区分实例）
        assert fired[0].key == 'api_health_fail'

    def test_single_spike_resets_window(self) -> None:
        ev = RuleEvaluator([_rule(for_s=30.0)])
        ev.feed('api', 'health_fail', 5, ts=0.0)
        ev.feed('api', 'health_fail', 5, ts=25.0)
        ev.feed('api', 'health_fail', 1, ts=29.0)  # 恢复 → 重置
        assert ev.feed('api', 'health_fail', 5, ts=35.0) == []  # 重新计时

    def test_key_per_service(self) -> None:
        """全局规则（service=''）按服务区分实例与去重键。"""
        ev = RuleEvaluator([_rule(service='', for_s=0.0)])
        a = ev.feed('web', 'health_fail', 9, ts=100.0)
        b = ev.feed('api', 'health_fail', 9, ts=100.0)
        assert a[0].key.endswith('@web') and b[0].key.endswith('@api')

    def test_reset_clears_breach(self) -> None:
        ev = RuleEvaluator([_rule(for_s=30.0)])
        ev.feed('api', 'health_fail', 5, ts=0.0)
        ev.reset()
        assert ev.feed('api', 'health_fail', 5, ts=10.0) == []


class TestInhibition:
    def test_explicit_chain(self) -> None:
        """pg_down 抑制 api_5xx（同服务）。"""
        inh = Inhibition(chain_rules=(('pg_down', ('api_5xx', 'api_health_fail')),))
        src = Alert(key='pg_down@pg', severity=Severity.P1, title='PG 不可用',
                    service='pg', family='pg_down')
        cand = Alert(key='api_5xx@api', severity=Severity.P2, title='5xx',
                     service='api', family='api_5xx')
        assert inh.find_suppressor(cand, [src]) == 'pg_down@pg(pg_down)'

    def test_implicit_severity(self) -> None:
        """同服务高级别 firing 时低级别不再产生（蓝鲸口径）。"""
        inh = Inhibition()
        high = Alert(key='api_down@api', severity=Severity.P0, title='API 停止',
                     service='api', family='availability')
        low = Alert(key='api_5xx@api', severity=Severity.P2, title='5xx',
                    service='api', family='api_5xx')
        assert inh.find_suppressor(low, [high])

    def test_no_cross_service_suppression(self) -> None:
        inh = Inhibition()
        high = Alert(key='pg_down@pg', severity=Severity.P0, title='PG',
                     service='pg', family='availability')
        low = Alert(key='api_5xx@api', severity=Severity.P2, title='5xx',
                    service='api', family='api_5xx')
        assert not inh.find_suppressor(low, [high])

    def test_explicit_rules_can_disable_implicit(self) -> None:
        inh = Inhibition(implicit_severity=False)
        high = Alert(key='a@api', severity=Severity.P0, title='h', service='api', family='x')
        low = Alert(key='b@api', severity=Severity.P2, title='l', service='api', family='y')
        assert not inh.find_suppressor(low, [high])


class TestSilence:
    def test_window_match(self) -> None:
        book = SilenceBook()
        book.add(Silence(id='s1', start_ts=100, end_ts=200, service='api', reason='维护'))
        assert book.match('api', 'availability', 150) is not None
        assert book.match('api', 'availability', 250) is None  # 过期
        assert book.match('web', 'availability', 150) is None  # 服务不匹配

    def test_family_scoped(self) -> None:
        book = SilenceBook()
        book.add(Silence(id='s1', start_ts=0, end_ts=100, family='saturation'))
        assert book.match('api', 'saturation', 50) is not None
        assert book.match('api', 'availability', 50) is None

    def test_add_validation_and_remove(self) -> None:
        book = SilenceBook()
        assert not book.add(Silence(id='bad', start_ts=100, end_ts=50)).ok
        assert book.add(Silence(id='ok', start_ts=0, end_ts=10)).ok
        assert not book.remove('missing').ok
        assert book.remove('ok').ok

    def test_prune_expired(self) -> None:
        book = SilenceBook()
        book.add(Silence(id='a', start_ts=0, end_ts=10))
        book.add(Silence(id='b', start_ts=0, end_ts=1000))
        assert book.prune(now=100) == 1
        assert book.active_count == 1


class TestAlertCenter:
    def test_raise_merge_cooldown(self) -> None:
        """收敛语义：60s 冷却 + 未确认合并（对齐 v6 行为并升级 count）。"""
        c = AlertCenter()
        a1 = Alert(key='k', severity=Severity.P1, title='t', ts=1000.0)
        d1 = c.ingest(a1, ts=1000.0)
        assert d1.action == 'raised' and d1.notify
        d2 = c.ingest(Alert(key='k', severity=Severity.P1, title='t', ts=1010.0), ts=1010.0)
        assert d2.action == 'cooled'  # 冷却期内忽略
        d3 = c.ingest(Alert(key='k', severity=Severity.P1, title='t', ts=1100.0), ts=1100.0)
        assert d3.action == 'merged'
        stored = c.get('k')
        assert stored is not None and stored.count == 2  # 原始 1 + 合并 1
        assert stored.ts == 1000.0  # 首次触发时间保留（MTTA 口径）

    def test_ack_and_badge(self) -> None:
        c = AlertCenter()
        c.ingest(Alert(key='k', severity=Severity.P2, title='t', ts=1000.0), ts=1000.0)
        assert c.unconfirmed_count() == 1
        assert c.ack('k', by='op', ts=1030.0).ok
        assert c.unconfirmed_count() == 0
        assert not c.ack('k').ok  # 重复确认失败
        assert not c.ack('missing').ok

    def test_resolve_allows_re_raise(self) -> None:
        """已恢复的告警不阻塞重新触发（新的一次事件）。"""
        c = AlertCenter()
        c.ingest(Alert(key='k', severity=Severity.P2, title='t', ts=0.0), ts=0.0)
        c.resolve('k', reason='ok', ts=100.0)
        d = c.ingest(Alert(key='k', severity=Severity.P2, title='t', ts=1000.0), ts=1000.0)
        assert d.action == 'raised'
        assert c.get('k').count == 1

    def test_silence_records_but_notifies_no(self) -> None:
        """静默期：只记不通知。"""
        book = SilenceBook()
        book.add(Silence(id='s', start_ts=0, end_ts=10_000, service='api', reason='维护'))
        c = AlertCenter(silences=book)
        d = c.ingest(Alert(key='k', severity=Severity.P0, title='t', service='api', ts=100.0), ts=100.0)
        assert d.action == 'silenced' and not d.notify and d.silence_id == 's'
        assert c.unconfirmed_count() == 1  # 已记录

    def test_inhibition_blocks_creation(self) -> None:
        """高级别存在 → 低级别不再产生（不入库），解除后可再次触发。"""
        inh = Inhibition()
        c = AlertCenter(inhibition=inh)
        c.ingest(Alert(key='hi@api', severity=Severity.P0, title='down',
                       service='api', family='availability', ts=0.0), ts=0.0)
        d = c.ingest(Alert(key='lo@api', severity=Severity.P2, title='5xx',
                           service='api', family='api_5xx', ts=10.0), ts=10.0)
        assert d.action == 'inhibited' and not d.notify
        assert c.get('lo@api') is None
        assert c.suppressed_total == 1
        c.resolve('hi@api', ts=100.0)
        d2 = c.ingest(Alert(key='lo@api', severity=Severity.P2, title='5xx',
                            service='api', family='api_5xx', ts=200.0), ts=200.0)
        assert d2.action == 'raised'

    def test_p4_never_notifies(self) -> None:
        c = AlertCenter()
        d = c.ingest(Alert(key='k', severity=Severity.P4, title='t', ts=0.0), ts=0.0)
        assert d.action == 'raised' and not d.notify

    def test_ack_all_and_stats(self) -> None:
        c = AlertCenter()
        c.ingest(Alert(key='a', severity=Severity.P2, title='t', ts=0.0), ts=0.0)
        c.ingest(Alert(key='b', severity=Severity.P3, title='t', ts=10.0), ts=10.0)
        assert c.ack_all(by='op', ts=30.0) == 2
        c.resolve('a', ts=60.0)
        c.resolve('b', ts=110.0)
        s = c.stats()
        assert s['mtta_s'] == 25.0  # (30-0 + 30-10)/2
        assert s['mttr_s'] == 80.0  # (60-0 + 110-10)/2

    def test_alerts_newest_first(self) -> None:
        c = AlertCenter()
        c.ingest(Alert(key='old', severity=Severity.P3, title='t', ts=0.0), ts=0.0)
        c.ingest(Alert(key='new', severity=Severity.P3, title='t', ts=500.0), ts=500.0)
        assert [a.key for a in c.alerts][:2] == ['new', 'old']

    def test_cap_100_prunes_resolved_first(self) -> None:
        """上限 100：溢出优先淘汰最早恢复的条目。"""
        c = AlertCenter()
        for i in range(99):
            c.ingest(Alert(key=f'k{i}', severity=Severity.P3, title='t', ts=i), ts=float(i))
        c.ingest(Alert(key='will_resolve', severity=Severity.P3, title='t', ts=200.0), ts=200.0)
        c.resolve('will_resolve', ts=250.0)
        assert len(c.alerts) == 100
        c.ingest(Alert(key='overflow', severity=Severity.P3, title='t', ts=300.0), ts=300.0)
        assert len(c.alerts) == 100
        assert c.get('will_resolve') is None  # 已恢复的被优先淘汰
        assert c.get('k0') is not None

    def test_resolve_matching_prefix(self) -> None:
        c = AlertCenter()
        c.ingest(Alert(key='sat@api', severity=Severity.P3, title='t', ts=0.0), ts=0.0)
        c.ingest(Alert(key='sat@web', severity=Severity.P3, title='t', ts=0.0), ts=0.0)
        c.ingest(Alert(key='other', severity=Severity.P3, title='t', ts=0.0), ts=0.0)
        assert c.resolve_matching('sat', reason='降载') == 2
        assert c.unconfirmed_count() == 1
