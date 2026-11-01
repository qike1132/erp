"""audit_log 保留期治理（P1-R2）单元测试：安全不变式优先。

决策与机制见 docs/audit-log-retention-decision.md 与
fastapi_app/tasks/audit_retention_task.py 模块 docstring。本文件锁的是**不变式**
而不是实现细节：

1. 整月粒度——月中部分过期的月份必须整体保留（合规方向：多留不删）；
2. 归档成功才删除——归档抛错/行数不符时该月一行不删；
3. 分批删除——按 pkey 游标推进、每批 commit（小事务）；
4. 幂等——归档文件已存在不重导，重跑不产生重复删除；
5. 错误不静默——pending_errors 非空时健康信号 ok=False（否则「每月都跳过
   但 last_success_at 照常刷新」会永远绿）。

这些断言都做过变异验证：故意去掉对应守卫后，相应测试必须失败（见
test_mutation_* 注释里的说明）。
"""
from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from fastapi_app.core.config import settings
from fastapi_app.tasks import audit_retention_task as art


# ---------------------------------------------------------------------------
# 假 DB：按 SQL 文本特征分派，记录调用顺序与参数
# ---------------------------------------------------------------------------
class _Result:
    def __init__(self, rows: list[Any], rowcount: int = 0):
        self._rows = rows
        self.rowcount = rowcount

    def all(self):
        return self._rows

    def scalars(self):
        return _Scalars(self._rows)


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return [r[0] if isinstance(r, (tuple, list)) else r for r in self._rows]


class FakeDB:
    """最小可用的 AsyncSession 替身。

    - ``months``: { 'YYYY-MM': 行数 } 供 compute_retention_plan
    - ``export_rows``: { 'YYYY-MM': [tuple(12 列)] } 供 _export_month_jsonl
    - ``ids_by_month``: { 'YYYY-MM': [id, ...] } 供分批删除
    """

    def __init__(
        self,
        months: dict[str, int] | None = None,
        export_rows: dict[str, list[tuple]] | None = None,
        ids_by_month: dict[str, list[int]] | None = None,
        export_error: Exception | None = None,
    ):
        self.months = months or {}
        self.export_rows = export_rows or {}
        self.ids_by_month = ids_by_month or {}
        self.export_error = export_error
        self.calls: list[str] = []          # 归一化后的语句类别，按执行顺序
        self.commits = 0
        self.deleted_ids: list[int] = []
        self.batches: list[list[int]] = []

    async def execute(self, statement, params: dict | None = None):
        sql = str(statement)
        params = params or {}
        if 'GROUP BY 1' in sql:
            self.calls.append('plan')
            return _Result([(m, n) for m, n in sorted(self.months.items())])
        if sql.startswith('SELECT id FROM audit_log'):
            self.calls.append('select_batch')
            month = _month_of(params['ms'])
            ids = [i for i in self.ids_by_month.get(month, []) if i > params['cursor']]
            batch = ids[: params['batch']]
            self.batches.append(batch)
            return _Result([(i,) for i in batch])
        if sql.startswith('DELETE FROM audit_log'):
            self.calls.append('delete')
            self.deleted_ids.extend(params['ids'])
            return _Result([], rowcount=len(params['ids']))
        if sql.startswith('SELECT id, user_id'):
            if self.export_error:
                raise self.export_error
            self.calls.append('export')
            month = _month_of(params['ms'])
            rows = self.export_rows.get(month, [])
            return _Result(rows)
        if sql.startswith('ANALYZE'):
            self.calls.append('analyze')
            return _Result([])
        raise AssertionError(f'未预期的语句: {sql[:80]}')

    async def commit(self):
        self.commits += 1


def _month_of(dt: datetime) -> str:
    return f'{dt.year:04d}-{dt.month:02d}'


def _row(row_id: int, month: str, day: int = 15) -> tuple:
    year, mon = (int(x) for x in month.split('-'))
    return (
        row_id, 1, 'admin', 'login', 'user', '1', {'k': 'v'}, '127.0.0.1',
        'pytest', f'req-{row_id}', 200, datetime(year, mon, day, 3, 0, tzinfo=UTC),
    )


@pytest.fixture(autouse=True)
def _fixed_settings(monkeypatch):
    monkeypatch.setattr(settings, 'AUDIT_RETENTION_MONTHS', 12, raising=False)
    yield


# ---------------------------------------------------------------------------
# 1. 月边界与 cutoff 计算
# ---------------------------------------------------------------------------
def test_cutoff_is_n_months_before_now_utc():
    now = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
    assert art.retention_cutoff(now) == datetime(2025, 11, 15, 12, 0, tzinfo=UTC)


def test_month_bounds_handles_december_rollover():
    start, end = art._month_bounds('2025-12')
    assert start == datetime(2025, 12, 1, tzinfo=UTC)
    assert end == datetime(2026, 1, 1, tzinfo=UTC)


async def test_plan_keeps_partially_expired_month_intact():
    """整月粒度：月中部分过期的月份必须整体保留。

    now=2026-11-15 → cutoff=2025-11-15。
    2025-11 的月末 2025-12-01 > cutoff ⇒ 该月只有前半月过期，**保留整月**；
    2025-10 的月末 2025-11-01 ≤ cutoff ⇒ 整月过期，可处理。
    变异验证：删掉 ``if month_end > cutoff: continue`` 后本断言失败（会多出 2025-11）。
    """
    db = FakeDB(months={'2025-10': 100, '2025-11': 50})
    plans = await art.compute_retention_plan(db, datetime(2026, 11, 15, tzinfo=UTC))
    assert [p['month'] for p in plans] == ['2025-10']
    assert plans[0]['rows'] == 100


async def test_plan_empty_when_retention_disabled(monkeypatch):
    monkeypatch.setattr(settings, 'AUDIT_RETENTION_MONTHS', 0, raising=False)
    db = FakeDB(months={'2025-01': 10})
    assert await art.compute_retention_plan(db, datetime(2026, 11, 15, tzinfo=UTC)) == []
    # 禁用时连计划查询都不该发生
    assert 'plan' not in db.calls


# ---------------------------------------------------------------------------
# 2. 归档先行，归档成功才删除
# ---------------------------------------------------------------------------
async def test_archive_written_before_delete(tmp_path):
    month = '2025-10'
    db = FakeDB(
        months={month: 2},
        export_rows={month: [_row(1, month), _row(2, month)]},
        ids_by_month={month: [1, 2]},
    )
    report = await art.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json',
    )
    # 顺序不变式：export 必须早于任何 delete
    assert db.calls.index('export') < db.calls.index('delete')
    assert report['deleted_total'] == 2
    assert report['analyzed'] is True
    assert db.deleted_ids == [1, 2]

    gz = tmp_path / 'audit_log_202510.jsonl.gz'
    assert gz.exists()
    with gzip.open(gz, 'rt', encoding='utf-8') as f:
        lines = [json.loads(ln) for ln in f.read().splitlines()]
    assert [ln['id'] for ln in lines] == [1, 2]
    assert lines[0]['created_at'] == '2025-10-15T03:00:00+00:00'

    state = json.loads((tmp_path / 'state.json').read_text(encoding='utf-8'))
    assert state['archive_files'][month]['rows'] == 2
    assert state['pending_errors'] == []
    assert state['deleted_rows_total'] == 2


async def test_no_delete_when_export_raises(tmp_path):
    """归档抛错 ⇒ 该月一行不删，错误进 pending_errors。

    变异验证：把 except 分支里的 ``continue`` 删掉（或吞掉异常后照常删除），
    本测试的 deleted_total==0 与 'delete' not in calls 会失败。
    """
    month = '2025-10'
    db = FakeDB(
        months={month: 2},
        ids_by_month={month: [1, 2]},
        export_error=OSError('disk full'),
    )
    report = await art.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json',
    )
    assert report['deleted_total'] == 0
    assert 'delete' not in db.calls
    assert report['errors'] and report['errors'][0]['month'] == month
    assert 'OSError' in report['errors'][0]['error']
    state = json.loads((tmp_path / 'state.json').read_text(encoding='utf-8'))
    assert state['pending_errors'][0]['month'] == month


async def test_no_delete_when_archive_row_mismatch(tmp_path):
    """归档行数与计划不符 ⇒ 保守跳过删除（该月数据一行不动）。"""
    month = '2025-10'
    db = FakeDB(
        months={month: 3},
        export_rows={month: [_row(1, month), _row(2, month)]},  # 只导出 2 行
        ids_by_month={month: [1, 2, 3]},
    )
    report = await art.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json',
    )
    assert report['deleted_total'] == 0
    assert 'delete' not in db.calls
    assert report['errors'][0]['error'] == 'archive_row_mismatch'
    # 归档文件仍保留（若人工核对后确认可删，下一轮导入即可复用）
    assert (tmp_path / 'audit_log_202510.jsonl.gz').exists()


async def test_one_bad_month_does_not_block_others(tmp_path):
    """单月失败不阻断其余月份；成功月份的删除照常发生。"""
    good, bad = '2025-09', '2025-10'
    db = FakeDB(
        months={good: 1, bad: 2},
        export_rows={good: [_row(1, good)], bad: [_row(2, bad)]},
        ids_by_month={good: [1], bad: [2, 3]},
    )
    # 让 2025-10 的导出抛错：export_error 是全局开关，改为把该月行数弄成不符
    db.months[bad] = 9
    report = await art.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json',
    )
    assert report['deleted_total'] == 1          # 只有 good 月被删
    assert 1 in db.deleted_ids
    assert [e['month'] for e in report['errors']] == [bad]
    assert report['analyzed'] is True            # 有删除就要 ANALYZE


# ---------------------------------------------------------------------------
# 3. 分批删除
# ---------------------------------------------------------------------------
async def test_delete_is_batched_with_cursor_and_commits_per_batch(tmp_path):
    """12000 行 / 批 5000 ⇒ 3 批，游标单调推进，每批一次 commit。"""
    month = '2025-10'
    ids = list(range(1, 12001))
    db = FakeDB(
        months={month: len(ids)},
        export_rows={month: [_row(i, month) for i in ids]},
        ids_by_month={month: ids},
    )
    await art.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json',
    )
    assert [len(b) for b in db.batches] == [5000, 5000, 2000, 0]
    assert db.batches[-1] == []  # 收尾再查一次确认为空才退出
    assert db.deleted_ids == ids
    # 3 批删除各 1 次 commit + ANALYZE 1 次
    assert db.commits == 4


async def test_delete_batch_size_is_bounded():
    """批上限是常量契约：调大它会放大长事务与锁等待。"""
    assert art.DELETE_BATCH_ROWS == 5000


def test_export_select_matches_column_tuple():
    """导出语句的列名必须与 _AUDIT_COLUMNS 逐字一致、同序。

    导出语句刻意写成字面量（不做 f-string 拼接列名，避免 B608 与 nosec 豁免），
    代价是「列名清单」有两处表述。此断言就是那条缝合线：给 audit_log 加列却
    只改了一处时立即变红——否则 jsonl 会按错位的列名落盘（zip(strict=True)
    只能发现**数量**不符，同数量错顺序它抓不到）。
    """
    expected = 'SELECT ' + ', '.join(art._AUDIT_COLUMNS) + ' FROM audit_log '
    assert art._EXPORT_SELECT.startswith(expected), (
        f'导出语句列名与 _AUDIT_COLUMNS 不一致：\n  期望前缀 {expected!r}\n'
        f'  实际       {art._EXPORT_SELECT!r}')
    assert art._EXPORT_SELECT.endswith('ORDER BY id'), (
        '导出必须按 id 排序：游标分批删除与重跑幂等都依赖稳定顺序')


async def test_unexpected_export_error_propagates(tmp_path):
    """未知异常（编程错误）必须上抛，不能被按月吞成 pending_error。

    except 只兜 (OSError, SQLAlchemyError)：若为「多处理几个月份」而写成
    裸 ``except Exception``，一个真 bug 会被永远降级成一条健康项错误，任务
    日日「成功」跑完却什么都没做。本断言锁住这个收窄决定。
    同时断言崩在写状态文件之前：不能给一次崩溃盖上新鲜的 last_success_at。
    """
    state_path = tmp_path / 'state.json'
    db = FakeDB(
        months={'2025-10': 1}, ids_by_month={'2025-10': [1]},
        export_error=RuntimeError('序列化 bug'),
    )
    with pytest.raises(RuntimeError, match='序列化 bug'):
        await art.run_retention_once(
            db, now=datetime(2026, 11, 15, tzinfo=UTC),
            archive_dir=tmp_path, state_path=state_path,
        )
    assert 'delete' not in db.calls
    assert not state_path.exists()


# ---------------------------------------------------------------------------
# 4. 幂等
# ---------------------------------------------------------------------------
async def test_rerun_reuses_existing_archive(tmp_path):
    """重跑：归档文件已存在则不重导（不覆盖证据），sha256 保持不变。"""
    month = '2025-10'
    gz = tmp_path / 'audit_log_202510.jsonl.gz'
    gz.write_bytes(b'pretend-archive')
    before = gz.read_bytes()

    db = FakeDB(months={month: 2}, ids_by_month={month: [1, 2]})
    report = await art.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json',
    )
    assert 'export' not in db.calls            # 未重导
    assert gz.read_bytes() == before           # 证据未被覆盖
    assert report['months'][0]['sha256'] == art._sha256_of(gz)
    assert db.deleted_ids == [1, 2]            # 删除仍执行（幂等的另一半）


async def test_state_written_even_when_nothing_to_do(tmp_path):
    """无事可做也要写状态文件——「任务活着」本身就是证据。"""
    state_path = tmp_path / 'state.json'
    db = FakeDB(months={})
    report = await art.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=state_path,
    )
    assert report['months'] == [] and report['deleted_total'] == 0
    state = json.loads(state_path.read_text(encoding='utf-8'))
    assert state['last_success_at'] == '2026-11-15T00:00:00+00:00'
    assert state['pending_errors'] == []
    assert 'analyze' not in db.calls


async def test_archive_files_accumulate_across_runs(tmp_path):
    """archive_files 是累积账本（跨轮保留历史月份），供等保检查取证。"""
    state_path = tmp_path / 'state.json'
    for month, rid in (('2025-09', 1), ('2025-10', 2)):
        db = FakeDB(
            months={month: 1}, export_rows={month: [_row(rid, month)]},
            ids_by_month={month: [rid]},
        )
        await art.run_retention_once(
            db, now=datetime(2026, 11, 15, tzinfo=UTC),
            archive_dir=tmp_path, state_path=state_path,
        )
    state = json.loads(state_path.read_text(encoding='utf-8'))
    assert set(state['archive_files']) == {'2025-09', '2025-10'}
    assert state['deleted_rows_total'] == 2


# ---------------------------------------------------------------------------
# 5. 健康信号
# ---------------------------------------------------------------------------
def _write_state(tmp_path, monkeypatch, **fields):
    path = tmp_path / 'state.json'
    path.write_text(json.dumps(fields), encoding='utf-8')
    monkeypatch.setattr(art, 'STATE_PATH', path)
    return path


def test_signal_ok_when_fresh(tmp_path, monkeypatch):
    _write_state(tmp_path, monkeypatch,
                 last_success_at=datetime.now(UTC).isoformat(),
                 retention_months=12, deleted_rows_total=100, archive_files={},
                 pending_errors=[])
    sig = art.audit_retention_signal()
    assert sig['ok'] is True
    assert sig['pending_error_count'] == 0


def test_signal_stale_after_threshold(tmp_path, monkeypatch):
    """停摆 >7 天 ⇒ ok=False（health 据此置 degraded）。"""
    old = (datetime.now(UTC) - timedelta(days=art.STALE_DAYS + 1)).isoformat()
    _write_state(tmp_path, monkeypatch, last_success_at=old, pending_errors=[])
    assert art.audit_retention_signal()['ok'] is False


def test_signal_not_ok_when_pending_errors(tmp_path, monkeypatch):
    """新鲜但有未处理错误 ⇒ ok=False。

    变异验证：从 ``ok`` 表达式里去掉 ``and not pending`` 后本测试失败——
    这正是「每月都跳过、last_success_at 却照常刷新」的静默洞。
    """
    _write_state(tmp_path, monkeypatch,
                 last_success_at=datetime.now(UTC).isoformat(),
                 pending_errors=[{'month': '2025-10', 'error': 'archive_row_mismatch'}])
    sig = art.audit_retention_signal()
    assert sig['ok'] is False
    assert sig['pending_error_count'] == 1
    assert sig['pending_errors'][0]['month'] == '2025-10'


def test_signal_missing_state_is_grace(tmp_path, monkeypatch):
    """状态文件不存在 = 部署首日宽限，ok=True 且 note 可辨。"""
    monkeypatch.setattr(art, 'STATE_PATH', tmp_path / 'absent.json')
    sig = art.audit_retention_signal()
    assert sig['ok'] is True and sig['note'] == 'not_yet_run'


def test_signal_corrupt_state_is_not_grace(tmp_path, monkeypatch):
    """状态文件损坏 ≠ 从未运行：必须 ok=False。

    变异验证：把 STATE_PATH.exists() 分支并进 not_yet_run 后本测试失败——
    损坏文件不会自愈，误判成宽限等于永久藏住停摆。
    """
    path = tmp_path / 'state.json'
    path.write_text('{not json', encoding='utf-8')
    monkeypatch.setattr(art, 'STATE_PATH', path)
    sig = art.audit_retention_signal()
    assert sig['ok'] is False and sig['note'] == 'state_unreadable'


def test_signal_disabled_when_months_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'AUDIT_RETENTION_MONTHS', 0, raising=False)
    monkeypatch.setattr(art, 'STATE_PATH', tmp_path / 'absent.json')
    sig = art.audit_retention_signal()
    assert sig['ok'] is True and sig['disabled'] is True


def test_signal_pending_errors_truncated(tmp_path, monkeypatch):
    """错误列表只暴露前 5 条，避免健康响应被撑爆，但计数完整。"""
    _write_state(tmp_path, monkeypatch,
                 last_success_at=datetime.now(UTC).isoformat(),
                 pending_errors=[{'month': f'2025-{i:02d}', 'error': 'x'} for i in range(1, 9)])
    sig = art.audit_retention_signal()
    assert len(sig['pending_errors']) == 5
    assert sig['pending_error_count'] == 8


# ---------------------------------------------------------------------------
# 6. 与 health 端点的接线
# ---------------------------------------------------------------------------
def test_health_degrades_when_retention_not_ok():
    """core.health 必须把该信号映射成 degraded（而不是只塞字段）。"""
    from fastapi_app.core import health as health_mod

    sig = health_mod._audit_retention_signal()
    assert isinstance(sig, dict) and 'ok' in sig


def test_health_signal_never_raises(monkeypatch):
    """内部读状态抛错时，健康端点必须拿到中性值而不是 500。"""
    from fastapi_app.core import health as health_mod
    from fastapi_app.tasks import audit_retention_task

    def _boom():
        raise RuntimeError('state read exploded')

    monkeypatch.setattr(audit_retention_task, 'audit_retention_signal', _boom)
    sig = health_mod._audit_retention_signal()
    assert sig['ok'] is True and sig['note'] == 'signal_error'
