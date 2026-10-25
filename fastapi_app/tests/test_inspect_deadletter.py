"""M-4（2026-10-25 上线前审计）：死信巡检脚本的汇总与判级。"""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.inspect_deadletter import main, summarize


def _write(tmp_path: Path, records: list[dict]) -> Path:
    p = tmp_path / 'deadletter.jsonl'
    p.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in records) + '\n',
                 encoding='utf-8')
    return p


def test_summarize_counts_stages_and_recent_window(tmp_path):
    now = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
    old_ts = (now - timedelta(days=30)).isoformat()
    new_ts = (now - timedelta(days=1)).isoformat()
    p = _write(tmp_path, [
        {'ts': new_ts, 'event_type': 'stock_out.created', 'error': 'Redis 广播未发出'},
        {'ts': new_ts, 'event_type': 'stock_out.created', 'error': 'Redis 广播未发出'},
        {'ts': old_ts, 'event_type': 'order.status_changed', 'error': 'Redis 广播未发出'},
        {'ts': new_ts, 'stage': 'handler', 'event_type': 'order.deleted',
         'handler': 'boom', 'error': 'cannot import name'},
        # 坏行必须被跳过而不是让巡检崩溃
    ])
    p.open('a', encoding='utf-8').write('{not-json}\n')
    s = summarize(p, days=7, now=now)
    assert s['total'] == 4
    assert s['by_stage'] == {'broadcast': 3, 'handler': 1}
    assert s['by_type']['stock_out.created'] == 2
    assert list(s['recent_by_day'].values()) == [3], '30 天前的旧广播死信不入近窗'
    assert len(s['handler_samples']) == 1


def test_main_exit_codes(tmp_path, capsys):
    broadcast_only = tmp_path / 'broadcast.jsonl'
    broadcast_only.write_text(json.dumps({
        'ts': datetime.now(UTC).isoformat(), 'event_type': 'stock_out.updated',
        'error': 'Redis 广播未发出',
    }, ensure_ascii=False) + '\n', encoding='utf-8')
    assert main(['--file', str(broadcast_only)]) == 0

    with_handler = tmp_path / 'handler.jsonl'
    with_handler.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in [
        {'ts': datetime.now(UTC).isoformat(), 'event_type': 'order.deleted',
         'error': 'Redis 广播未发出'},
        {'ts': datetime.now(UTC).isoformat(), 'stage': 'handler_cross_process',
         'handler': 'h', 'event_type': 'order.deleted', 'error': 'boom'},
    ]) + '\n', encoding='utf-8')
    assert main(['--file', str(with_handler)]) == 2, 'handler 级死信必须 exit 2 引起注意'
    out = capsys.readouterr().out
    assert 'handler_cross_process' in out
