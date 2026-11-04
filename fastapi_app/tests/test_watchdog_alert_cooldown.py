"""watchdog 告警冷却记账（2026-11-04 修复回归）。

缺陷：``scripts/ops/watchdog.py`` 原先在 ``select_alerts()`` 里就把 ``last_sent = now``
写进 state，而真正的投递发生在之后的 ``notify()``。于是当**没有任何可用告警通道**
（BACKUP_ALERT_WEBHOOK_ENABLED 未开 + SMTP 未配置，新机默认状态）或**所有通道都
发送失败**时：

- 告警一条都没送出去，却已在 state 里被记成「已告警」；
- 后续 WATCHDOG_ALERT_COOLDOWN_MINUTES（默认 30 分钟）内不再尝试；
- 运维在 ``logs/watchdog_state.json`` 里看到的是「已通知」，与事实相反。

修复后的契约（本文件逐条锁定）：
1. ``select_alerts`` 只读冷却状态，不写 ``last_sent``；
2. ``record_alerts_sent`` 仅在 ``channels`` 非空时推进冷却；
3. 未投递时留下 ``undelivered_attempts`` / ``undelivered_since`` 痕迹；
4. 未投递不阻塞下一轮（下一次 select 仍会选中同一告警）；
5. 成功投递后进入冷却（冷却期内不再重复告警）；
6. main() 在未投递时不因此改写冷却、退出码仍只由检查项状态决定。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def watchdog() -> ModuleType:
    """按路径加载零依赖脚本（与 test_web_health_probe_scheme.py 同款加载方式）。"""
    spec = importlib.util.spec_from_file_location(
        "erp_watchdog_cooldown_under_test", ROOT / "scripts" / "ops" / "watchdog.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # 先注册进 sys.modules：`from __future__ import annotations` 下 dataclass 解析
    # 字符串注解要按 __module__ 反查模块，缺席会直接抛错。
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    yield mod
    sys.modules.pop(spec.name, None)


def _failed(watchdog: ModuleType, key: str = "backup_freshness") -> object:
    return watchdog.CheckResult(key, "备份新鲜度", watchdog.FAIL, "最新备份 300 分钟前")


# --------------------------------------------------------------- 冷却记账单元契约

def test_select_alerts_does_not_advance_cooldown(watchdog) -> None:
    """缺陷本体：挑选阶段不得把 last_sent 写进 state。"""
    state: dict = {}
    result = _failed(watchdog)

    selected = watchdog.select_alerts([result], state, cooldown_minutes=30)

    assert [r.key for r in selected] == [result.key]
    assert state['alerts'] == {}, '未投递前不允许写冷却记账'


def test_undelivered_alert_is_retried_next_round(watchdog) -> None:
    """无通道时必须下一轮继续告警（原实现会静默 30 分钟）。"""
    state: dict = {}
    result = _failed(watchdog)

    first = watchdog.select_alerts([result], state, cooldown_minutes=30)
    watchdog.record_alerts_sent(state, first, channels=[])  # 一个通道都没成功
    second = watchdog.select_alerts([result], state, cooldown_minutes=30)

    assert [r.key for r in second] == [result.key]
    entry = state['alerts'][result.key]
    assert 'last_sent' not in entry
    assert entry['undelivered_attempts'] == 1
    assert entry['undelivered_since']
    assert entry['status'] == watchdog.FAIL


def test_undelivered_attempts_accumulate(watchdog) -> None:
    """连续多轮都发不出去时，attempts 累加（运维可据此发现通道长期失效）。"""
    state: dict = {}
    result = _failed(watchdog)
    for _ in range(3):
        pending = watchdog.select_alerts([result], state, cooldown_minutes=30)
        watchdog.record_alerts_sent(state, pending, channels=[])

    assert state['alerts'][result.key]['undelivered_attempts'] == 3
    assert 'last_sent' not in state['alerts'][result.key]


def test_successful_delivery_advances_cooldown(watchdog) -> None:
    """投递成功后进入冷却：冷却期内不再重复告警。"""
    state: dict = {}
    result = _failed(watchdog)

    pending = watchdog.select_alerts([result], state, cooldown_minutes=30)
    watchdog.record_alerts_sent(state, pending, channels=['webhook'], sent_at=1_700_000_000)

    entry = state['alerts'][result.key]
    assert entry['last_sent'] == 1_700_000_000
    assert entry['channels'] == ['webhook']
    assert 'undelivered_attempts' not in entry


def test_delivery_clears_previous_undelivered_trace(watchdog, monkeypatch) -> None:
    """先失败后成功：undelivered 痕迹要被清掉，冷却按成功时刻推进。"""
    state: dict = {}
    result = _failed(watchdog)

    pending = watchdog.select_alerts([result], state, cooldown_minutes=30)
    watchdog.record_alerts_sent(state, pending, channels=[])
    assert state['alerts'][result.key]['undelivered_attempts'] == 1

    pending = watchdog.select_alerts([result], state, cooldown_minutes=30)
    watchdog.record_alerts_sent(state, pending, channels=['email'], sent_at=1_700_000_000)

    entry = state['alerts'][result.key]
    assert entry['last_sent'] == 1_700_000_000
    assert 'undelivered_attempts' not in entry
    assert 'undelivered_since' not in entry


def test_recovery_still_clears_cooldown(watchdog) -> None:
    """恢复正常的检查项必须清掉冷却记录（不受本次修复影响）。"""
    state = {'alerts': {'backup_freshness': {'last_sent': 1, 'status': watchdog.FAIL}}}
    ok = watchdog.CheckResult('backup_freshness', '备份新鲜度', watchdog.OK, '最新 5 分钟前')

    selected = watchdog.select_alerts([ok], state, cooldown_minutes=30)

    assert selected == []
    assert 'backup_freshness' not in state['alerts']


def test_no_alerts_means_no_state_write(watchdog) -> None:
    """无告警时 record 是 no-op（不得凭空创建 alerts 结构）。"""
    state: dict = {}
    watchdog.record_alerts_sent(state, [], channels=[])
    assert state == {}


# --------------------------------------------------------------- main() 端到端

def _run_main(watchdog, monkeypatch, tmp_path: Path, *, failed: bool,
              channels: list[str]) -> tuple[int, dict, list[bool]]:
    """跑一轮 main()，把检查项与通道全部打桩，返回 (退出码, state, 投递调用记录)。"""
    calls: list[bool] = []

    # 不打桩 load_env_file 的话，main 会把真实 .env 灌进 os.environ（单个用例
    # 不该有跨用例的进程级副作用）；本文件测的是冷却记账，与环境加载无关。
    monkeypatch.setattr(watchdog, 'load_env_file', lambda path: 0)

    def _fake_run_checks(options):
        status = watchdog.FAIL if failed else watchdog.OK
        return [watchdog.CheckResult('backup_freshness', '备份新鲜度', status, '桩数据')]

    def _fake_notify(alerts, results, timeout):
        calls.append(bool(alerts))
        return list(channels)

    monkeypatch.setattr(watchdog, 'run_checks', _fake_run_checks)
    monkeypatch.setattr(watchdog, 'notify', _fake_notify)
    monkeypatch.setenv('WATCHDOG_STATE_FILE', str(tmp_path / 'watchdog_state.json'))
    monkeypatch.setenv('WATCHDOG_LOG_FILE', str(tmp_path / 'watchdog.log'))
    monkeypatch.setenv('WATCHDOG_BACKUP_DIR', str(tmp_path))
    monkeypatch.delenv('BACKUP_ALERT_WEBHOOK_ENABLED', raising=False)
    monkeypatch.delenv('BACKUP_ALERT_EMAIL_ENABLED', raising=False)

    code = watchdog.main(['--json'])
    state = json.loads((tmp_path / 'watchdog_state.json').read_text(encoding='utf-8'))
    return code, state, calls


def test_main_without_channels_keeps_alert_retryable(watchdog, monkeypatch, tmp_path) -> None:
    """端到端：没有任何通道时，state 不得标记为已告警，且退出码仍为 1。"""
    code, state, calls = _run_main(watchdog, monkeypatch, tmp_path, failed=True, channels=[])

    assert code == 1, '检查项失败时退出码必须为 1（与是否送达无关）'
    assert calls == [True], '有异常项就必须尝试投递'
    entry = state['alerts']['backup_freshness']
    assert 'last_sent' not in entry
    assert entry['undelivered_attempts'] == 1
    log_text = (tmp_path / 'watchdog.log').read_text(encoding='utf-8')
    assert '告警未投递' in log_text, '未送达必须在日志里显式可见'


def test_main_with_channel_records_cooldown(watchdog, monkeypatch, tmp_path) -> None:
    """端到端：成功投递后写入冷却，第二轮不再重复告警。"""
    code, state, calls = _run_main(watchdog, monkeypatch, tmp_path, failed=True, channels=['webhook'])

    assert code == 1
    assert calls == [True]
    assert state['alerts']['backup_freshness']['last_sent'] > 0
    assert state['alerts']['backup_freshness']['channels'] == ['webhook']


def test_main_all_ok_clears_state(watchdog, monkeypatch, tmp_path) -> None:
    """全部正常：退出码 0，且不产生告警记账。"""
    code, state, calls = _run_main(watchdog, monkeypatch, tmp_path, failed=False, channels=['webhook'])

    assert code == 0
    assert calls == [], '无异常项不应调用投递'
    assert state['alerts'] == {}
