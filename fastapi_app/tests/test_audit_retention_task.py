"""audit_log 保留期治理（P1-R2）单元测试：安全不变式优先。

决策与机制见 docs/audit-log-retention-decision.md 与
fastapi_app/tasks/audit_retention_task.py 模块 docstring。本文件锁的是**不变式**
而不是实现细节：

1. 整月粒度——月中部分过期的月份必须整体保留（合规方向：多留不删）；
2. 删除范围 ⊆ 归档覆盖范围——删除谓词带归档的 max_id 上界；复用既有归档时
   校验剩余行是其子集，不完整则中止（评审 H1）；
3. 归档失败/行数不符 ⇒ 该月一行不删（含删除阶段失败：下一轮可安全续删）；
4. 分批——导出与删除都按批，删除每批 commit；
5. 幂等——归档已存在不重导；重跑续删剩余部分；
6. 错误不静默——pending_errors 非空时健康信号 ok=False；任务整体失败也写状态
   （否则「天天失败」被读成「从未运行」而永久宽限）；
7. 时区口径显式 UTC——不依赖会话 TimeZone（生产是 Asia/Shanghai）。

标注「变异验证」的断言都实测过：施加对应破坏后该测试必须变红。
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
    def __init__(self, rows: list[Any], rowcount: int = 0, scalar: Any = None):
        self._rows = rows
        self.rowcount = rowcount
        self._scalar = scalar

    def all(self):
        return self._rows

    def one(self):
        return self._rows[0]

    def scalar(self):
        return self._scalar

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
    - ``export_rows``: { 'YYYY-MM': [tuple(12 列)] } 供 _export_month_jsonl（支持分页）
    - ``ids_by_month``: { 'YYYY-MM': [id, ...] } 供分批删除
    - ``export_error`` / ``delete_error``: 在对应阶段抛出
    """

    def __init__(
        self,
        months: dict[str, int] | None = None,
        export_rows: dict[str, list[tuple]] | None = None,
        ids_by_month: dict[str, list[int]] | None = None,
        export_error: Exception | None = None,
        delete_error: Exception | None = None,
        delete_error_month: str | None = None,
    ):
        self.months = months or {}
        self.export_rows = export_rows or {}
        self.ids_by_month = ids_by_month or {}
        self.export_error = export_error
        self.delete_error = delete_error
        self.delete_error_month = delete_error_month
        self.calls: list[str] = []          # 归一化后的语句类别，按执行顺序
        self.commits = 0
        self.deleted_ids: list[int] = []
        self.batches: list[list[int]] = []
        self.export_max_ids: list[int | None] = []   # 每次导出请求的 max_id 上界
        self.plan_sql = ''
        self._current_month: str | None = None

    async def execute(self, statement, params: dict | None = None):
        sql = str(statement)
        params = params or {}
        if 'GROUP BY 1' in sql:
            self.calls.append('plan')
            self.plan_sql = sql
            return _Result([(m, n) for m, n in sorted(self.months.items())])
        if sql.startswith('SELECT count(*)'):
            self.calls.append('window_stats')
            month = _month_of(params['ms'])
            ids = self.ids_by_month.get(month, [])
            return _Result([(len(ids), max(ids) if ids else 0)])
        if sql.startswith('SELECT id FROM audit_log'):
            self.calls.append('select_batch')
            month = _month_of(params['ms'])
            self._current_month = month
            if self.delete_error and self.delete_error_month in (None, month):
                raise self.delete_error
            # 假替身按**收到的 SQL 文本**决定是否施加 max_id 上界：替身自己
            # 无条件过滤会把「SQL 忘了写 id <= :max_id」这类回归掩盖掉（第一轮
            # 变异验证就栽在这里——M1 存活）。替身越笨，测试越真。
            bounded = 'id <= :max_id' in sql
            ids = [i for i in self.ids_by_month.get(month, [])
                   if params['cursor'] < i and (not bounded or i <= params['max_id'])]
            batch = ids[: params['batch']]
            self.batches.append(batch)
            return _Result([(i,) for i in batch])
        if sql.startswith('DELETE FROM audit_log'):
            self.calls.append('delete')
            if self.delete_error and self.delete_error_month in (None, self._current_month):
                raise self.delete_error
            self.deleted_ids.extend(params['ids'])
            return _Result([], rowcount=len(params['ids']))
        if sql.startswith('SELECT id, user_id'):
            if self.export_error:
                raise self.export_error
            self.calls.append('export')
            self.export_max_ids.append(params.get('max_id'))
            month = _month_of(params['ms'])
            rows = [r for r in self.export_rows.get(month, []) if r[0] > params['cursor']]
            return _Result(rows[: params['batch']])
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


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    """默认把 STATE_PATH 指到临时目录，避免测试读写真实 logs/ 状态文件。"""
    monkeypatch.setattr(art, 'STATE_PATH', tmp_path / 'default_state.json')
    yield


# ---------------------------------------------------------------------------
# 1. 月边界与 cutoff 计算（时区口径显式 UTC）
# ---------------------------------------------------------------------------
def test_cutoff_is_n_months_before_now_utc():
    now = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
    assert art.retention_cutoff(now) == datetime(2025, 11, 15, 12, 0, tzinfo=UTC)


def test_month_bounds_handles_december_rollover():
    start, end = art._month_bounds('2025-12')
    assert start == datetime(2025, 12, 1, tzinfo=UTC)
    assert end == datetime(2026, 1, 1, tzinfo=UTC)


async def test_plan_buckets_months_in_utc_not_session_timezone():
    """月键必须显式按 UTC 折算。

    生产会话时区是 Asia/Shanghai（实测 SHOW TimeZone），而 date_trunc/to_char
    对 timestamptz 按会话时区折算——用会话口径分桶会让月键与 UTC 导出/删除窗
    差 8 小时（实测 2026-10 差 303 行），首轮必然 archive_row_mismatch。
    变异验证：把 SQL 改回 date_trunc('month', created_at) 后本断言失败。
    """
    db = FakeDB(months={'2025-10': 1})
    await art.compute_retention_plan(db, datetime(2026, 11, 15, tzinfo=UTC))
    assert "AT TIME ZONE 'UTC'" in db.plan_sql
    assert 'date_trunc' not in db.plan_sql   # 会话时区口径已被排除


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
    assert 'plan' not in db.calls   # 禁用时连计划查询都不该发生


async def test_plan_refuses_below_statutory_minimum(monkeypatch):
    """配置 0 < months < 6 → 拒绝执行（误配不能变成静默的过度删除）。

    变异验证：删掉 compute_retention_plan 里的 MIN_RETENTION_MONTHS 分支，
    本测试会看到 3 个月的计划被算出来并执行删除。
    """
    monkeypatch.setattr(settings, 'AUDIT_RETENTION_MONTHS', 3, raising=False)
    db = FakeDB(months={'2026-01': 10})
    assert await art.compute_retention_plan(db, datetime(2026, 11, 15, tzinfo=UTC)) == []
    assert 'plan' not in db.calls
    assert art.audit_retention_signal()['misconfigured'] is True


# ---------------------------------------------------------------------------
# 2. 归档先行 + 删除范围 ⊆ 归档覆盖范围（评审 H1）
# ---------------------------------------------------------------------------
async def test_archive_written_before_delete_and_bounded_by_max_id(tmp_path):
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
    assert report['months'][0]['archive_max_id'] == 2

    gz = tmp_path / 'audit_log_202510.jsonl.gz'
    assert gz.exists()
    with gzip.open(gz, 'rt', encoding='utf-8') as f:
        lines = [json.loads(ln) for ln in f.read().splitlines()]
    assert [ln['id'] for ln in lines] == [1, 2]
    assert lines[0]['created_at'] == '2025-10-15T03:00:00+00:00'

    state = json.loads((tmp_path / 'state.json').read_text(encoding='utf-8'))
    assert state['archive_files'][month]['rows'] == 2
    assert state['archive_files'][month]['max_id'] == 2
    assert state['pending_errors'] == []
    assert state['deleted_rows_total'] == 2


async def test_delete_stops_at_archive_max_id(tmp_path):
    """导出之后才落进窗口的行（id > max_id）绝不能被删。

    构造：导出时只有 id 1..2，删除阶段库里又多出 id 3（补录/回放）。删除谓词
    带 ``id <= max_id``：3 必须保留。
    变异验证：去掉 _delete_month_batched 的 ``AND id <= :max_id`` 后本测试失败
    （3 会被删掉，而它从未进过归档）。
    """
    month = '2025-10'
    db = FakeDB(
        months={month: 2},
        export_rows={month: [_row(1, month), _row(2, month)]},
        ids_by_month={month: [1, 2, 3]},   # 删除阶段能看到 3
    )
    report = await art.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json',
    )
    assert db.deleted_ids == [1, 2]
    assert 3 not in db.deleted_ids
    assert report['months'][0]['archive_max_id'] == 2


async def test_incomplete_archive_blocks_delete_on_reuse(tmp_path):
    """复用既有归档时，剩余行必须是归档的子集；否则中止（不删）。

    构造：归档里只有 id 1..2（max_id=2），库里却还有 id 3 —— 3 从未归档，
    删它就等于毁证据。旧实现只看「文件存在」→ 照删。
    变异验证：把复用分支的子集校验删掉（回到只看 existed）后本测试失败。
    """
    month = '2025-10'
    gz = tmp_path / 'audit_log_202510.jsonl.gz'
    with gzip.open(gz, 'wt', encoding='utf-8') as f:
        for i in (1, 2):
            f.write(json.dumps(dict(zip(art._AUDIT_COLUMNS, _row(i, month), strict=True)),
                               default=str) + '\n')

    db = FakeDB(months={month: 3}, ids_by_month={month: [1, 2, 3]})
    report = await art.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json',
    )
    assert db.deleted_ids == []
    assert report['errors'][0]['error'] == 'archive_incomplete'
    assert report['errors'][0]['remaining_max_id'] == 3
    state = json.loads((tmp_path / 'state.json').read_text(encoding='utf-8'))
    assert state['pending_errors'][0]['error'] == 'archive_incomplete'


async def test_corrupt_archive_is_not_reused(tmp_path):
    """截断/损坏的归档（掉电后常见）必须当成错误，而不是「文件存在就删」。

    变异验证：把 _export_month_jsonl 的 archive_stats 换成 exists() 判断后，
    本测试的 deleted_ids 会变成 [1, 2]（数据被删而证据不可读）。
    """
    month = '2025-10'
    gz = tmp_path / 'audit_log_202510.jsonl.gz'
    gz.write_bytes(b'\x1f\x8b\x08\x00truncated-not-a-valid-gzip')

    db = FakeDB(months={month: 2}, ids_by_month={month: [1, 2]})
    report = await art.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json',
    )
    assert db.deleted_ids == []
    assert report['errors'][0]['error'].startswith('OSError')


async def test_reuse_is_idempotent_and_resumes_deletion(tmp_path):
    """重跑：归档已存在不重导；上次没删完的（崩溃/中断）本轮续删。

    归档 1..2、库里也只剩 1..2 ⇒ 子集校验通过（rows>=remaining 且
    max_remaining<=max_id）⇒ 继续删除。旧实现把 rows 记成 -1 且跳过一切校验。
    """
    month = '2025-10'
    gz = tmp_path / 'audit_log_202510.jsonl.gz'
    with gzip.open(gz, 'wt', encoding='utf-8') as f:
        for i in (1, 2):
            f.write(json.dumps(dict(zip(art._AUDIT_COLUMNS, _row(i, month), strict=True)),
                               default=str) + '\n')
    before = gz.read_bytes()

    db = FakeDB(months={month: 2}, ids_by_month={month: [1, 2]})
    report = await art.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json',
    )
    assert 'export' not in db.calls            # 未重导
    assert gz.read_bytes() == before           # 证据未被覆盖
    assert db.deleted_ids == [1, 2]            # 删除仍继续
    assert report['errors'] == []
    assert report['months'][0]['sha256'] == art._sha256_of(gz)


async def test_no_delete_when_export_raises(tmp_path):
    """归档抛错 ⇒ 该月一行不删，错误进 pending_errors。"""
    month = '2025-10'
    db = FakeDB(months={month: 2}, ids_by_month={month: [1, 2]},
                export_error=OSError('disk full'))
    report = await art.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json',
    )
    assert report['deleted_total'] == 0
    assert 'delete' not in db.calls
    assert 'OSError' in report['errors'][0]['error']
    state = json.loads((tmp_path / 'state.json').read_text(encoding='utf-8'))
    assert state['pending_errors'][0]['month'] == month


async def test_no_delete_when_archive_row_mismatch(tmp_path):
    """本次导出行数与计划不符 ⇒ 保守跳过删除（该月数据一行不动）。"""
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
    assert (tmp_path / 'audit_log_202510.jsonl.gz').exists()


async def test_delete_failure_skips_only_that_month(tmp_path):
    """删除阶段失败：该月留错误、其余月份照常删除。

    评审 L1：删除失败原先不在兜底范围内，一个死锁会连累后续所有月份。
    变异验证：把 _delete_month_batched 移出 try 块后，本测试会看到异常上抛。
    """
    good, bad = '2025-09', '2025-10'
    db = FakeDB(
        months={good: 1, bad: 2},
        export_rows={good: [_row(1, good)], bad: [_row(2, bad), _row(3, bad)]},
        ids_by_month={good: [1], bad: [2, 3]},
        delete_error=OSError('lock timeout'),
        delete_error_month=bad,
    )
    report = await art.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json',
    )
    assert db.deleted_ids == [1]                       # good 月照删
    assert [e['month'] for e in report['errors']] == [bad]
    assert 'OSError' in report['errors'][0]['error']
    assert report['analyzed'] is True                  # 有删除仍要 ANALYZE


async def test_unexpected_export_error_propagates(tmp_path):
    """未知异常（编程错误）必须上抛，不能被按月吞成 pending_error。

    except 只兜 (OSError, SQLAlchemyError)：若为「多处理几个月份」而写成
    裸 ``except Exception``，一个真 bug 会被永远降级成一条健康项错误。
    同时断言崩在写状态文件之前：不能给一次崩溃盖上新鲜的 last_success_at。
    """
    state_path = tmp_path / 'state.json'
    db = FakeDB(months={'2025-10': 1}, ids_by_month={'2025-10': [1]},
                export_error=RuntimeError('序列化 bug'))
    with pytest.raises(RuntimeError, match='序列化 bug'):
        await art.run_retention_once(
            db, now=datetime(2026, 11, 15, tzinfo=UTC),
            archive_dir=tmp_path, state_path=state_path,
        )
    assert 'delete' not in db.calls
    assert not state_path.exists()


# ---------------------------------------------------------------------------
# 3. 分批（导出与删除）
# ---------------------------------------------------------------------------
async def test_delete_is_batched_with_cursor_and_commits_per_batch(tmp_path):
    """12000 行 / 批 5000 ⇒ 3 批 + 收尾空查，游标单调推进，每批一次 commit。"""
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
    assert db.batches[-1] == []
    assert db.deleted_ids == ids
    assert db.commits == 4          # 3 批删除各 1 次 + ANALYZE 1 次


async def test_export_is_batched_not_fully_materialised(tmp_path):
    """整月导出必须分批读（评审 M6：25 万行 × detail 全量物化会打爆内存）。

    12000 行 / 批 5000 ⇒ 4 次导出查询（5000、5000、2000、收尾空查）。
    变异验证：把导出改回一次性 SELECT（不分页）后 export 只会被调用 1 次。
    """
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
    assert db.calls.count('export') == 4


def test_batch_sizes_are_bounded():
    """批上限是常量契约：调大它会放大长事务/内存峰值。"""
    assert art.DELETE_BATCH_ROWS == 5000
    assert art.EXPORT_BATCH_ROWS == 5000


# ---------------------------------------------------------------------------
# 4. 幂等与状态文件
# ---------------------------------------------------------------------------
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
        db = FakeDB(months={month: 1}, export_rows={month: [_row(rid, month)]},
                    ids_by_month={month: [rid]})
        await art.run_retention_once(
            db, now=datetime(2026, 11, 15, tzinfo=UTC),
            archive_dir=tmp_path, state_path=state_path,
        )
    state = json.loads(state_path.read_text(encoding='utf-8'))
    assert set(state['archive_files']) == {'2025-09', '2025-10'}
    assert state['deleted_rows_total'] == 2


async def test_corrupt_state_is_set_aside_not_silently_reset(tmp_path):
    """状态文件损坏 → 另存为 .corrupt-*（留现场）+ 本轮报错，而不是静默清零。

    评审 M2：旧实现 ``read() or {}`` 把 archive_files / deleted_rows_total
    清零重建，且顺手清空 pending_errors——「自愈」得毫无痕迹，等保账本没了。
    """
    state_path = tmp_path / 'state.json'
    state_path.write_text('{not json', encoding='utf-8')

    db = FakeDB(months={})
    report = await art.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=state_path,
    )
    assert report['errors'] == [{'month': None, 'error': 'state_corrupt_recovered'}]
    corrupt = list(tmp_path.glob('state.json.corrupt-*'))
    assert len(corrupt) == 1 and corrupt[0].read_text(encoding='utf-8') == '{not json'
    state = json.loads(state_path.read_text(encoding='utf-8'))
    assert state['pending_errors'][0]['error'] == 'state_corrupt_recovered'


def test_write_failure_state_records_attempt_and_keeps_ledger(tmp_path):
    """任务整体失败也要留痕：写 last_attempt_at/last_error，保留既有账本。

    评审 M3：没有这一步，「天天失败」的状态文件永不生成 → 健康端点永远停在
    not_yet_run 宽限而恒绿。
    """
    state_path = tmp_path / 'state.json'
    state_path.write_text(json.dumps({
        'archive_files': {'2025-09': {'path': 'x', 'rows': 1, 'max_id': 1, 'sha256': 'y'}},
        'deleted_rows_total': 7,
    }), encoding='utf-8')

    art.write_failure_state(RuntimeError('boom'), state_path)
    state = json.loads(state_path.read_text(encoding='utf-8'))
    assert state['last_error'] == 'RuntimeError: boom'
    assert 'last_attempt_at' in state
    assert 'last_success_at' not in state
    assert state['archive_files']['2025-09']['rows'] == 1    # 账本没被清
    assert state['deleted_rows_total'] == 7


async def test_task_writes_failure_state_and_releases_lock(monkeypatch, tmp_path):
    """ARQ 入口：任务体抛错时先写 last_attempt_at/last_error，再释放锁并上抛。

    评审 M3：状态文件原先只在成功后写，于是「天天失败」的表现与「从未运行」
    完全相同 → 健康端点永久宽限恒绿。变异验证：删掉 finally 里的
    write_failure_state 调用后本测试失败。
    """
    state_path = tmp_path / 'state.json'

    class _FakeSession:
        def __init__(self):
            self.calls: list[str] = []

        async def execute(self, statement, params=None):
            self.calls.append(str(statement).split('(')[0].strip())
            return _Result([], scalar=True)

        async def commit(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    session = _FakeSession()

    async def _boom(db):
        raise RuntimeError('plan query failed')

    monkeypatch.setattr(art, 'require_async_session_local', lambda: (lambda: session))
    monkeypatch.setattr(art, 'run_retention_once', _boom)
    monkeypatch.setattr(art, 'STATE_PATH', state_path)

    with pytest.raises(RuntimeError, match='plan query failed'):
        await art.audit_retention_task({})

    state = json.loads(state_path.read_text(encoding='utf-8'))
    assert state['last_error'] == 'RuntimeError: plan query failed'
    assert 'last_success_at' not in state
    # 锁必须被释放（连接回池后会话仍在，锁不会自己消失）
    assert any('pg_advisory_unlock' in c for c in session.calls)


async def test_task_skips_when_lock_busy(monkeypatch, tmp_path):
    """拿不到锁时干净退出：不写成功态、不把自己算成失败。"""
    state_path = tmp_path / 'state.json'

    class _FakeSession:
        def __init__(self):
            self.calls: list[str] = []

        async def execute(self, statement, params=None):
            self.calls.append(str(statement))
            return _Result([], scalar=False)   # pg_try_advisory_lock → false

        async def commit(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    session = _FakeSession()
    monkeypatch.setattr(art, 'require_async_session_local', lambda: (lambda: session))
    monkeypatch.setattr(art, 'STATE_PATH', state_path)

    result = await art.audit_retention_task({})
    assert result == {'skipped': 'lock_busy'}
    assert not state_path.exists()          # 另一实例负责写状态
    assert not any('pg_advisory_unlock' in c for c in session.calls)  # 没拿到就不解锁


# ---------------------------------------------------------------------------
# 5. 健康信号
# ---------------------------------------------------------------------------
def _write_signal_state(tmp_path, monkeypatch, **fields):
    path = tmp_path / 'state.json'
    path.write_text(json.dumps(fields), encoding='utf-8')
    monkeypatch.setattr(art, 'STATE_PATH', path)
    return path


def test_signal_ok_when_fresh(tmp_path, monkeypatch):
    _write_signal_state(tmp_path, monkeypatch,
                        last_success_at=datetime.now(UTC).isoformat(),
                        retention_months=12, deleted_rows_total=100,
                        archive_files={}, pending_errors=[])
    sig = art.audit_retention_signal()
    assert sig['ok'] is True
    assert sig['pending_error_count'] == 0


def test_signal_stale_after_threshold(tmp_path, monkeypatch):
    """停摆 >7 天 ⇒ ok=False（health 据此置 degraded）。"""
    old = (datetime.now(UTC) - timedelta(days=art.STALE_DAYS + 1)).isoformat()
    _write_signal_state(tmp_path, monkeypatch, last_success_at=old, pending_errors=[])
    assert art.audit_retention_signal()['ok'] is False


def test_signal_not_ok_when_pending_errors(tmp_path, monkeypatch):
    """新鲜但有未处理错误 ⇒ ok=False。

    变异验证：从 ok 表达式里去掉 ``and not pending`` 后本测试失败——这正是
    「每月都跳过、last_success_at 却照常刷新」的静默洞。
    """
    _write_signal_state(tmp_path, monkeypatch,
                        last_success_at=datetime.now(UTC).isoformat(),
                        pending_errors=[{'month': '2025-10', 'error': 'archive_incomplete'}])
    sig = art.audit_retention_signal()
    assert sig['ok'] is False
    assert sig['pending_error_count'] == 1
    assert sig['pending_errors'][0]['month'] == '2025-10'


def test_signal_missing_state_is_grace(tmp_path, monkeypatch):
    """状态文件不存在 = 从未运行（宽限），ok=True 且 note 可辨。"""
    monkeypatch.setattr(art, 'STATE_PATH', tmp_path / 'absent.json')
    sig = art.audit_retention_signal()
    assert sig['ok'] is True and sig['note'] == 'not_yet_run'


def test_signal_corrupt_state_is_not_grace(tmp_path, monkeypatch):
    """状态文件损坏 ≠ 从未运行：必须 ok=False。"""
    path = tmp_path / 'state.json'
    path.write_text('{not json', encoding='utf-8')
    monkeypatch.setattr(art, 'STATE_PATH', path)
    sig = art.audit_retention_signal()
    assert sig['ok'] is False and sig['note'] == 'state_unreadable'


def test_signal_bad_timestamp_is_not_grace(tmp_path, monkeypatch):
    """JSON 合法但 last_success_at 坏/缺失 ⇒ 也必须 ok=False（评审 M1）。

    旧实现这里返回 ok=True，与上面「损坏当异常」的结论相反——同一个函数对
    「损坏」给了两个答案，且这条分支无测试。
    变异验证：把该分支改回 ok=True 后本测试失败。
    """
    path = tmp_path / 'state.json'
    path.write_text(json.dumps({'last_success_at': ''}), encoding='utf-8')
    monkeypatch.setattr(art, 'STATE_PATH', path)
    assert art.audit_retention_signal()['ok'] is False

    path.write_text(json.dumps({'last_success_at': 'not-a-time'}), encoding='utf-8')
    assert art.audit_retention_signal()['ok'] is False


def test_signal_naive_timestamp_is_interpreted_as_utc(tmp_path, monkeypatch):
    """naive 时间戳（手改/旧格式）不能让函数抛错，也不能逃成 signal_error。

    旧实现 datetime.now(UTC) - naive 抛 TypeError，被 health 兜成 ok=True。
    """
    naive = datetime.now(UTC).replace(tzinfo=None).isoformat()
    _write_signal_state(tmp_path, monkeypatch, last_success_at=naive, pending_errors=[])
    sig = art.audit_retention_signal()
    assert sig['ok'] is True
    assert sig['age_days'] < 1


def test_signal_failed_run_only_is_not_grace(tmp_path, monkeypatch):
    """只有 last_attempt_at、没有 last_success_at ⇒ ok=False。

    对应「任务天天失败」：状态文件被 write_failure_state 写出来了，但没有成功记录。
    """
    path = tmp_path / 'state.json'
    path.write_text(json.dumps({
        'last_attempt_at': datetime.now(UTC).isoformat(),
        'last_error': 'RuntimeError: boom',
        'archive_files': {},
    }), encoding='utf-8')
    monkeypatch.setattr(art, 'STATE_PATH', path)
    sig = art.audit_retention_signal()
    assert sig['ok'] is False
    assert sig['note'] == 'state_unreadable'
    assert sig['last_error'] == 'RuntimeError: boom'


def test_signal_disabled_when_months_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'AUDIT_RETENTION_MONTHS', 0, raising=False)
    monkeypatch.setattr(art, 'STATE_PATH', tmp_path / 'absent.json')
    sig = art.audit_retention_signal()
    assert sig['ok'] is True and sig['disabled'] is True


def test_signal_pending_errors_truncated(tmp_path, monkeypatch):
    """错误列表只暴露前 5 条，避免健康响应被撑爆，但计数完整。"""
    _write_signal_state(tmp_path, monkeypatch,
                        last_success_at=datetime.now(UTC).isoformat(),
                        pending_errors=[{'month': f'2025-{i:02d}', 'error': 'x'}
                                        for i in range(1, 9)])
    sig = art.audit_retention_signal()
    assert len(sig['pending_errors']) == 5
    assert sig['pending_error_count'] == 8


# ---------------------------------------------------------------------------
# 6. 与 health 端点的接线（评审 M7：原断言恒真）
# ---------------------------------------------------------------------------
def test_status_resolution_maps_retention_to_degraded():
    """状态判定是对外可观测承诺，必须能被单测直接打。

    变异验证：把 _resolve_status 里 audit_retention_ok 的参与删掉后本测试失败。
    """
    from fastapi_app.core.health import _resolve_status

    assert _resolve_status(True, True, True) == 'healthy'
    assert _resolve_status(True, True, False) == 'degraded'      # 仅保留治理异常
    assert _resolve_status(True, False, True) == 'degraded'      # 仅备份链异常
    assert _resolve_status(True, False, False) == 'degraded'
    assert _resolve_status(False, True, True) == 'unhealthy'     # DB 死活优先


async def test_health_degrades_end_to_end(monkeypatch, tmp_path):
    """驱动 _build_fresh_health：保留治理不 ok 时 status 必须是 degraded。

    不 mock 状态文件，而是直接让信号返回 ok=False，验证的是「接线」而非「信号」。
    变异验证：把 _resolve_status 调用换回原先的内联 if（或删掉 audit_retention
    分支）后本测试失败——原先那条 ``'ok' in sig`` 断言对它完全无感。
    """
    from fastapi_app.core import health as health_mod

    async def _db_ok():
        return True

    async def _backup_ok():
        return {'ok': True, 'age_hours': 1.0, 'arq_ok': True}

    async def _no_redis():
        return None

    monkeypatch.setattr(health_mod, 'verify_db_connectivity', _db_ok)
    monkeypatch.setattr(health_mod, '_backup_signal', _backup_ok)
    monkeypatch.setattr(health_mod, '_audit_retention_signal',
                        lambda: {'ok': False, 'pending_error_count': 1})
    monkeypatch.setattr(health_mod, '_set_cached_health', lambda **kw: None)
    monkeypatch.setattr('fastapi_app.core.redis_client.get_async_redis_client', _no_redis)

    data = await health_mod._build_fresh_health(user_id=None, reasons=[])
    assert data['status'] == 'degraded'
    assert data['audit_retention']['ok'] is False


def test_health_signal_never_raises(monkeypatch):
    """内部读状态抛错时，健康端点必须拿到中性值而不是 500。"""
    from fastapi_app.core import health as health_mod
    from fastapi_app.tasks import audit_retention_task

    def _boom():
        raise RuntimeError('state read exploded')

    monkeypatch.setattr(audit_retention_task, 'audit_retention_signal', _boom)
    sig = health_mod._audit_retention_signal()
    assert sig['ok'] is True and sig['note'] == 'signal_error'
