"""audit_log 保留期治理（P1-R2）单元测试：安全不变式优先。

决策与机制见 docs/audit-log-retention-decision.md 与
fastapi_app/tasks/audit_retention_task.py 模块 docstring。本文件锁的是**不变式**
而不是实现细节：

1. 整月粒度——月中部分过期的月份必须整体保留（合规方向：多留不删）；
2. **删除对象就是归档过的 id**——按 id 集合删、不按时间窗；删完复核窗口剩余，
   有未归档行则报 archive_incomplete 且不删；
3. 归档失败/行数不符/归档损坏 ⇒ 该月不进删除（删除阶段失败也隔离）；
4. 分批——导出与删除都按批，删除每批 commit；
5. 幂等——归档已存在不重导；崩溃后重跑续删；
6. 错误不静默——pending_errors 非空时健康信号 ok=False；任务整体失败写
   last_attempt_at；因锁跳过也要留痕；
7. 时区口径显式 UTC——不依赖会话 TimeZone（生产是 Asia/Shanghai）；
8. 单实例——锁必须绑在**专用连接**上（会话 commit 会换连接）。

标注「变异验证」的断言都实测过：施加对应破坏后该测试必须变红。
"""
from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

from fastapi_app.core.config import settings
from fastapi_app.tasks import audit_retention_task as art


# ---------------------------------------------------------------------------
# 假 DB：按 SQL 文本特征分派，**按 created_at 真实判窗**（不做「聪明」的过滤）
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


def _month_of(dt: datetime) -> str:
    return f'{dt.year:04d}-{dt.month:02d}'


def _row(row_id: int, month: str, day: int = 15) -> tuple:
    year, mon = (int(x) for x in month.split('-'))
    return (
        row_id, 1, 'admin', 'login', 'user', '1', {'k': 'v'}, '127.0.0.1',
        'pytest', f'req-{row_id}', 200, datetime(year, mon, day, 3, 0, tzinfo=UTC),
    )


class FakeDB:
    """最小可用的 AsyncSession 替身。

    表数据以 ``rows``（{月份: [12 列元组]}）为唯一真来源：导出按 id 分页、
    窗口计数**按 created_at 判窗**、删除会真的把行从表里去掉。替身越笨，
    「SQL 参数传错/谓词写反」这类回归越藏不住（复审 M-4）。
    """

    def __init__(
        self,
        months: dict[str, int] | None = None,
        export_rows: dict[str, list[tuple]] | None = None,
        ids_by_month: dict[str, list[int]] | None = None,
        export_error: Exception | None = None,
        delete_error: Exception | None = None,
        delete_error_month: str | None = None,
        delete_error_after: int | None = None,
        analyze_error: Exception | None = None,
        hidden_ids: set[int] | None = None,
    ):
        self.months = months or {}
        self.export_error = export_error
        self.delete_error = delete_error
        self.delete_error_month = delete_error_month
        # 前 N 次 DELETE 成功、之后才抛：模拟「第 2 批锁超时」（已提交批不丢账）
        self.delete_error_after = delete_error_after
        # ANALYZE 失败：模拟「删除已在 aborted 事务里中止，ANALYZE 抛 25P02」
        self.analyze_error = analyze_error
        # 导出时看不到、但确实在表里的 id：模拟「导出完成后才落进该窗口」的行
        self.hidden_ids = hidden_ids or set()
        self.calls: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.deleted_ids: list[int] = []
        self.delete_batches: list[list[int]] = []
        self.plan_sql = ''
        self._current_month: str | None = None

        self.rows: dict[str, list[tuple]] = {
            m: list(rs) for m, rs in (export_rows or {}).items()
        }
        # 只在 ids_by_month 里出现的行 = 「库里还有、但归档里没有」
        for m, ids in (ids_by_month or {}).items():
            known = {r[0] for r in self.rows.get(m, [])}
            for i in ids:
                if i not in known:
                    self.rows.setdefault(m, []).append(_row(i, m))

    def _in_window(self, params: dict) -> list[tuple]:
        ms, me = params['ms'], params['me']
        assert ms < me, f'窗口参数写反了: ms={ms} me={me}'
        return [r for r in self.rows.get(_month_of(ms), []) if ms <= r[11] < me]

    async def execute(self, statement, params: dict | None = None):
        sql = str(statement)
        params = params or {}
        if 'GROUP BY 1' in sql:
            self.calls.append('plan')
            self.plan_sql = sql
            return _Result([(m, n) for m, n in sorted(self.months.items())])
        if sql.startswith('SELECT count(*)'):
            self.calls.append('window_count')
            n = len(self._in_window(params))
            return _Result([(n,)], scalar=n)
        if sql.startswith('SELECT id, user_id'):
            if self.export_error:
                raise self.export_error
            self.calls.append('export')
            rows = sorted((r for r in self._in_window(params)
                           if r[0] > params['cursor'] and r[0] not in self.hidden_ids),
                          key=lambda r: r[0])
            return _Result(rows[: params['batch']])
        if sql.startswith('DELETE FROM audit_log'):
            self.calls.append('delete')
            chunk = list(params['ids'])
            month = next((m for m, rs in self.rows.items()
                          if any(r[0] in chunk for r in rs)), None)
            already = len(self.delete_batches)
            if (self.delete_error and self.delete_error_month in (None, month)
                    and (self.delete_error_after is None
                         or already >= self.delete_error_after)):
                raise self.delete_error
            existing = {r[0] for m in self.rows for r in self.rows[m]}
            matched = [i for i in chunk if i in existing]
            self.delete_batches.append(chunk)
            self.deleted_ids.extend(matched)
            for m in list(self.rows):
                self.rows[m] = [r for r in self.rows[m] if r[0] not in chunk]
            return _Result([], rowcount=len(matched))
        if sql.startswith('ANALYZE'):
            self.calls.append('analyze')
            if self.analyze_error:
                raise self.analyze_error
            return _Result([])
        raise AssertionError(f'未预期的语句: {sql[:80]}')

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        # 删除失败后会话停在 aborted 事务里，任务会用 rollback 把会话救回来
        self.rollbacks += 1


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
# 1. 月边界、cutoff、时区口径
# ---------------------------------------------------------------------------
def test_cutoff_is_n_months_before_now_utc():
    now = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
    assert art.retention_cutoff(now) == datetime(2025, 11, 15, 12, 0, tzinfo=UTC)


def test_month_bounds_handles_december_rollover():
    start, end = art._month_bounds('2025-12')
    assert start == datetime(2025, 12, 1, tzinfo=UTC)
    assert end == datetime(2026, 1, 1, tzinfo=UTC)


def test_archive_dir_relative_anchored_to_project_root(tmp_path):
    """归档目录同样锚定项目根（评审 L-4）：worker 与手工补跑 CWD 不同也不能分身。"""
    assert art.archive_dir_path('backups/audit_archive').is_absolute()
    assert art.archive_dir_path('backups/audit_archive') == (
        art._PROJECT_ROOT / 'backups/audit_archive')
    absolute = art.archive_dir_path(str(tmp_path))
    assert absolute == tmp_path


async def test_plan_buckets_months_in_utc_not_session_timezone():
    """月键必须显式按 UTC 折算。

    生产会话时区是 Asia/Shanghai（实测 SHOW TimeZone），而 date_trunc/to_char
    对 timestamptz 按会话时区折算——用会话口径分桶会让月键与 UTC 导出窗差 8
    小时（实测 2026-10 差 303 行），首轮必然 archive_row_mismatch。
    变异验证：把 SQL 改回 date_trunc('month', created_at) 后本断言失败。
    """
    db = FakeDB(months={'2025-10': 1})
    await art.compute_retention_plan(db, datetime(2026, 11, 15, tzinfo=UTC))
    assert "AT TIME ZONE 'UTC'" in db.plan_sql
    assert 'date_trunc' not in db.plan_sql


async def test_plan_keeps_partially_expired_month_intact():
    """整月粒度：月中部分过期的月份必须整体保留。

    now=2026-11-15 → cutoff=2025-11-15。
    2025-11 的月末 2025-12-01 > cutoff ⇒ 该月只有前半月过期，**保留整月**；
    2025-10 的月末 2025-11-01 ≤ cutoff ⇒ 整月过期，可处理。
    变异验证：删掉 ``if month_end > cutoff: continue`` 后本断言失败。
    """
    db = FakeDB(months={'2025-10': 100, '2025-11': 50})
    plans = await art.compute_retention_plan(db, datetime(2026, 11, 15, tzinfo=UTC))
    assert [p['month'] for p in plans] == ['2025-10']
    assert plans[0]['rows'] == 100


async def test_plan_empty_when_retention_disabled(monkeypatch):
    monkeypatch.setattr(settings, 'AUDIT_RETENTION_MONTHS', 0, raising=False)
    db = FakeDB(months={'2025-01': 10})
    assert await art.compute_retention_plan(db, datetime(2026, 11, 15, tzinfo=UTC)) == []
    assert 'plan' not in db.calls


async def test_plan_refuses_below_statutory_minimum(monkeypatch):
    """配置 0 < months < 6 → 拒绝执行（误配不能变成静默的过度删除）。"""
    monkeypatch.setattr(settings, 'AUDIT_RETENTION_MONTHS', 3, raising=False)
    db = FakeDB(months={'2026-01': 10})
    assert await art.compute_retention_plan(db, datetime(2026, 11, 15, tzinfo=UTC)) == []
    assert 'plan' not in db.calls
    assert art.audit_retention_signal()['misconfigured'] is True


# ---------------------------------------------------------------------------
# 2. 删除对象 == 归档过的 id（评审 H1 / M-1 / M-2 的核心）
# ---------------------------------------------------------------------------
async def test_archive_written_before_delete(tmp_path):
    month = '2025-10'
    db = FakeDB(months={month: 2}, ids_by_month={month: [1, 2]})
    report = await art.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json',
    )
    assert db.calls.index('export') < db.calls.index('delete')
    assert report['deleted_total'] == 2
    assert report['errors'] == []
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
    assert state['archive_files'][month]['path'].endswith('audit_log_202510.jsonl.gz')
    assert state['pending_errors'] == []
    assert state['deleted_rows_total'] == 2


async def test_delete_covers_exactly_the_archived_ids(tmp_path):
    """导出之后才落进该月的行（不在归档 id 里）绝不能被删。

    构造：库里 1,2,3，导出时只有 1,2 在窗口内（3 是导出后补录的）。
    删除只按归档 id ⇒ 3 存活；随后复核发现窗口还剩 1 行 ⇒ archive_incomplete。
    变异验证：把删除改回「按时间窗」后本测试失败（3 会被删掉且无错误）。
    """
    month = '2025-10'
    db = FakeDB(months={month: 2}, ids_by_month={month: [1, 2]})
    report = await art.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json',
    )
    # 此刻库里只有 1,2（3 尚未出现）——先断言正常路径
    assert db.deleted_ids == [1, 2]
    assert report['errors'] == []

    # 第二轮：补录行 3 出现在同一窗口（id 大于已归档的最大 id 也一样处理）
    db2 = FakeDB(months={month: 2}, ids_by_month={month: [1, 2, 3]},
                 hidden_ids={3})   # 3 在导出之后才落进该窗口
    report2 = await art.run_retention_once(
        db2, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state2.json',
    )
    assert 3 not in db2.deleted_ids          # 从未归档，绝不删
    assert report2['errors'][0]['error'] == 'archive_incomplete'
    assert report2['errors'][0]['remaining_rows'] == 1
    assert 'remediation' in report2['errors'][0]


async def test_leftover_unarchived_rows_report_has_remediation(tmp_path):
    """未归档行留下时必须给处置步骤（否则永久 degraded 无人知道怎么修）。"""
    month = '2025-10'
    db = FakeDB(months={month: 1}, ids_by_month={month: [1, 2]}, hidden_ids={2})
    report = await art.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json',
    )
    err = report['errors'][0]
    assert err['error'] == 'archive_incomplete'
    assert 'superseded' in err['remediation']
    state = json.loads((tmp_path / 'state.json').read_text(encoding='utf-8'))
    assert state['pending_errors'][0]['error'] == 'archive_incomplete'


async def test_delete_that_exceeds_window_is_reported(tmp_path):
    """归档被改名复用/来自别的环境时，删除会越出本月窗口 —— 必须报出来。

    构造成 2025-10 的窗口里只有 1、2，但归档文件（被人改名复用）里还有 900，
    而 900 属于 2025-09。按 id 删除会跨月删掉 900：`deleted(3) > before(2)`
    就是唯一的信号——`window_count` 只看本月，看不出越界。
    变异验证：去掉 `if deleted > before` 分支后本测试失败（静默返回无 error）。
    """
    month = '2025-10'
    gz = tmp_path / 'audit_log_202510.jsonl.gz'
    with gzip.open(gz, 'wt', encoding='utf-8') as f:
        for i in (1, 2, 900):
            f.write(json.dumps(dict(zip(art._AUDIT_COLUMNS, _row(i, month), strict=True)),
                               default=str) + '\n')

    db = FakeDB(months={month: 2}, ids_by_month={'2025-10': [1, 2], '2025-09': [900]})
    report = await art.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json',
    )
    err = report['errors'][0]
    assert err['error'] == 'delete_exceeded_window'
    assert err['deleted_rows'] == 3 and err['window_rows_before'] == 2
    assert 'remediation' in err
    state = json.loads((tmp_path / 'state.json').read_text(encoding='utf-8'))
    assert state['pending_errors'][0]['error'] == 'delete_exceeded_window'


async def test_corrupt_archive_is_not_reused(tmp_path):
    """截断/损坏的归档（掉电后常见）必须当成错误，而不是「文件存在就删」。

    变异验证：把 _export_month_jsonl 的 archive_stats 换成 exists() 判断后，
    本测试的 delete 调用会出现（数据被删而证据不可读）。
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
    assert report['errors'][0]['error'] == 'archive_failed'
    assert 'OSError' in report['errors'][0]['detail']


async def test_reuse_is_idempotent_and_resumes_deletion(tmp_path):
    """重跑：归档已存在不重导；上次没删完的（崩溃/中断）本轮续删。

    归档 1,2 且库里也只剩 1,2 ⇒ 续删干净、无错误。旧实现把 rows 记成 -1
    并跳过一切校验。
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
    assert db.deleted_ids == [1, 2]            # 续删
    assert report['errors'] == []
    assert report['months'][0]['sha256'] == art._sha256_of(gz)


async def test_partial_delete_then_rerun_is_clean(tmp_path):
    """上一轮删了一半（如崩溃）：本轮只删剩下的，不复核出假错误。"""
    month = '2025-10'
    gz = tmp_path / 'audit_log_202510.jsonl.gz'
    with gzip.open(gz, 'wt', encoding='utf-8') as f:
        for i in (1, 2, 3):
            f.write(json.dumps(dict(zip(art._AUDIT_COLUMNS, _row(i, month), strict=True)),
                               default=str) + '\n')

    db = FakeDB(months={month: 2}, ids_by_month={month: [2, 3]})   # 1 已删
    report = await art.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json',
    )
    assert db.deleted_ids == [2, 3]
    assert report['errors'] == []


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
    # 归档失败也要把会话从 aborted 事务里救回来，否则后续月份的错误全是 25P02
    assert db.rollbacks >= 1
    assert report['errors'][0]['error'] == 'archive_failed'
    assert 'OSError' in report['errors'][0]['detail']
    state = json.loads((tmp_path / 'state.json').read_text(encoding='utf-8'))
    assert state['pending_errors'][0]['month'] == month


async def test_no_delete_when_archive_row_mismatch(tmp_path):
    """本次导出行数与计划不符 ⇒ 本轮跳过删除（下一轮复用归档自愈）。"""
    month = '2025-10'
    db = FakeDB(months={month: 3}, ids_by_month={month: [1, 2, 3]}, hidden_ids={3})
    report = await art.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json',
    )
    assert report['deleted_total'] == 0
    assert 'delete' not in db.calls
    assert report['errors'][0]['error'] == 'archive_row_mismatch'
    assert 'remediation' in report['errors'][0]
    assert (tmp_path / 'audit_log_202510.jsonl.gz').exists()


async def test_delete_failure_skips_only_that_month(tmp_path):
    """删除阶段失败：该月留错误、其余月份照常删除（评审 L1）。"""
    good, bad = '2025-09', '2025-10'
    db = FakeDB(months={good: 1, bad: 2}, ids_by_month={good: [1], bad: [2, 3]},
                delete_error=OSError('lock timeout'), delete_error_month=bad)
    report = await art.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json',
    )
    assert db.deleted_ids == [1]
    assert [e['month'] for e in report['errors']] == [bad]
    assert report['analyzed'] is True


async def test_delete_failure_keeps_archive_in_ledger(tmp_path):
    """删除阶段失败 ≠ 归档白做：账本必须留下该月的 path/sha256。

    等保检查要看的是「这份证据在哪、指纹是多少」。删除失败时若把 entry 降级成
    「未归档」，磁盘上有文件、账本上没记录，取证链就断了一环。
    """
    month = '2025-10'
    db = FakeDB(months={month: 2}, ids_by_month={month: [1, 2]},
                delete_error=SQLAlchemyError('lock timeout'), delete_error_month=month)
    report = await art.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json',
    )
    entry = report['months'][0]
    assert entry['archived'] is True
    assert entry['archive_path'].endswith('audit_log_202510.jsonl.gz')
    assert len(entry['sha256']) == 64
    assert report['errors'][0]['error'] == 'delete_failed'
    assert 'remediation' in report['errors'][0]

    state = json.loads((tmp_path / 'state.json').read_text(encoding='utf-8'))
    assert state['archive_files'][month]['sha256'] == entry['sha256']


async def test_partial_delete_is_accounted(tmp_path):
    """第 2 批失败：第 1 批已经 commit 了，账本必须记这 5000 行。

    `_delete_ids_batched` 每批一次 commit —— 失败时异常上抛会带走累计值，
    账本于是比库「少记」。等保检查看的就是这份账本，少记=对不上。
    变异验证：去掉 progress 计数（固定 deleted:0）后本测试失败。
    """
    month = '2025-10'
    ids = list(range(1, 12001))
    db = FakeDB(months={month: len(ids)}, ids_by_month={month: ids},
                delete_error=SQLAlchemyError('lock timeout'), delete_error_after=1)
    report = await art.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json',
    )
    assert report['deleted_total'] == 5000          # 第 1 批已提交
    assert report['months'][0]['deleted'] == 5000
    assert report['analyzed'] is True               # 有删除就要 ANALYZE
    err = report['errors'][0]
    assert err['error'] == 'delete_failed' and err['deleted_rows'] == 5000
    # 删除失败后必须把会话从 aborted 事务里救回来，否则后续 ANALYZE 抛 25P02
    assert db.rollbacks >= 1


async def test_analyze_failure_does_not_swallow_the_report(tmp_path):
    """ANALYZE 失败（aborted 事务里抛 25P02）不能把整轮报告和账本一起吞掉。

    真实链路：某月删除分批中 PG 报错 → 会话停在 aborted 事务 → 有删除的轮次会
    接着跑 ANALYZE → 25P02。若这里不兜，`run_retention_once` 整体抛出，
    ① 根因被 25P02 覆盖；② 已提交的删除不进账本；③ 其它月份的成功结果全丢，
    健康端点从「degraded + delete_failed」退化成「stale/never_succeeded」。
    变异验证：去掉 ANALYZE 的 try/except 后本测试失败（run_retention_once 抛出）。
    """
    month = '2025-10'
    db = FakeDB(months={month: 2}, ids_by_month={month: [1, 2]},
                analyze_error=SQLAlchemyError('current transaction is aborted'))
    report = await art.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json',
    )
    assert report['deleted_total'] == 2          # 删除结果不丢
    assert report['analyzed'] is False
    assert report['errors'][0]['error'] == 'analyze_failed'
    state = json.loads((tmp_path / 'state.json').read_text(encoding='utf-8'))
    assert state['last_success_at']               # 账本照常落盘
    assert state['deleted_rows_total'] == 2


async def test_corrupt_ledger_is_reported_not_silently_zeroed(tmp_path):
    """账本里的 deleted_rows_total 被手改成非法值：按 0 起算，但必须留可见错误。

    静默归零等于「账本凭空消失且无痕迹」，与状态文件损坏时的处理（另存 + 报错）
    自相矛盾；等保检查看的就是这个累计值。
    """
    state_path = tmp_path / 'state.json'
    state_path.write_text(json.dumps({
        'deleted_rows_total': '1,234', 'archive_files': {},
    }), encoding='utf-8')
    db = FakeDB(months={})
    report = await art.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=state_path,
    )
    assert report['errors'][0]['error'] == 'ledger_corrupt'
    state = json.loads(state_path.read_text(encoding='utf-8'))
    assert state['deleted_rows_total'] == 0
    assert state['pending_errors'][0]['error'] == 'ledger_corrupt'
    # 原文件另存现场 + 原值长期保留（只报一轮等于没留痕）
    assert list(tmp_path.glob('state.json.corrupt-*'))
    assert state['deleted_rows_total_corrupt']['value'] == '1,234'

    # 第二轮：pending_errors 清空，但「账本被动过」这件事仍然可见
    db2 = FakeDB(months={})
    report2 = await art.run_retention_once(
        db2, now=datetime(2026, 11, 16, tzinfo=UTC),
        archive_dir=tmp_path, state_path=state_path,
    )
    assert report2['errors'] == []
    state2 = json.loads(state_path.read_text(encoding='utf-8'))
    assert state2['deleted_rows_total_corrupt']['value'] == '1,234'

    # bool 是 int 子类：{"deleted_rows_total": true} 也必须判成损坏（不能用 isinstance）
    p2 = tmp_path / 'state_bool.json'
    p2.write_text(json.dumps({'deleted_rows_total': True}), encoding='utf-8')
    report3 = await art.run_retention_once(
        FakeDB(months={}), now=datetime(2026, 11, 17, tzinfo=UTC),
        archive_dir=tmp_path, state_path=p2,
    )
    assert report3['errors'][0]['error'] == 'ledger_corrupt'


async def test_unexpected_export_error_propagates(tmp_path):
    """未知异常（编程错误）必须上抛，不能被按月吞成 pending_error。"""
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
# 3. 分批
# ---------------------------------------------------------------------------
async def test_delete_is_batched_and_commits_per_batch(tmp_path):
    """12000 行 / 批 5000 ⇒ 3 批删除，每批一次 commit（+ ANALYZE 一次）。"""
    month = '2025-10'
    ids = list(range(1, 12001))
    db = FakeDB(months={month: len(ids)}, ids_by_month={month: ids})
    await art.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json',
    )
    assert [len(b) for b in db.delete_batches] == [5000, 5000, 2000]
    assert db.deleted_ids == ids
    assert db.commits == 4          # 3 批 + ANALYZE


async def test_export_is_batched_not_fully_materialised(tmp_path):
    """整月导出必须分批读（评审 M6：25 万行 × detail 全量物化会打爆内存）。"""
    month = '2025-10'
    ids = list(range(1, 12001))
    db = FakeDB(months={month: len(ids)}, ids_by_month={month: ids})
    await art.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json',
    )
    assert db.calls.count('export') == 4      # 5000、5000、2000、收尾空查
    assert art.EXPORT_BATCH_ROWS == 5000
    assert art.DELETE_BATCH_ROWS == 5000


async def test_fsync_happens_after_gzip_trailer(tmp_path, monkeypatch):
    """fsync 必须在 gzip 尾部**写完之后**。

    ``GzipFile`` 只在 close() 时才补 CRC 尾部：若在 gzip 关闭前 fsync，落盘的
    是没有尾部的半截归档，而下一轮凭「文件存在」就会拿它去删源数据（评审 H1
    的持久化分支）。这里用事件顺序把这条顺序钉住。
    变异验证：删掉 os.fsync、或把它挪到 gzip with 之前，本测试失败。
    """
    month = '2025-10'
    order: list[str] = []
    real_close = gzip.GzipFile.close

    def _close(self):
        order.append('gzip_close')
        return real_close(self)

    def _fsync(_fd):
        order.append('fsync')

    monkeypatch.setattr(gzip.GzipFile, 'close', _close)
    monkeypatch.setattr(art.os, 'fsync', _fsync)

    db = FakeDB(months={month: 1}, ids_by_month={month: [1]})
    await art.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json',
    )
    assert 'gzip_close' in order and 'fsync' in order
    assert order.index('gzip_close') < order.index('fsync')
    # 归档读到底（CRC 校验通过）说明尾部确实写全了
    with gzip.open(tmp_path / 'audit_log_202510.jsonl.gz', 'rt', encoding='utf-8') as f:
        assert len(f.read().splitlines()) == 1


def test_export_select_matches_column_tuple():
    """导出语句的列名必须与 _AUDIT_COLUMNS 逐字一致、同序。"""
    expected = 'SELECT ' + ', '.join(art._AUDIT_COLUMNS) + ' FROM audit_log '
    assert art._EXPORT_SELECT.startswith(expected)
    assert art._EXPORT_SELECT.endswith('ORDER BY id LIMIT :batch')


# ---------------------------------------------------------------------------
# 4. 状态文件
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
        db = FakeDB(months={month: 1}, ids_by_month={month: [rid]})
        await art.run_retention_once(
            db, now=datetime(2026, 11, 15, tzinfo=UTC),
            archive_dir=tmp_path, state_path=state_path,
        )
    state = json.loads(state_path.read_text(encoding='utf-8'))
    assert set(state['archive_files']) == {'2025-09', '2025-10'}
    assert state['deleted_rows_total'] == 2


async def test_corrupt_state_is_set_aside_not_silently_reset(tmp_path):
    """状态文件损坏 → 另存为 .corrupt-*（留现场）+ 本轮报错，而不是静默清零。"""
    state_path = tmp_path / 'state.json'
    state_path.write_text('{not json', encoding='utf-8')

    db = FakeDB(months={})
    report = await art.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=state_path,
    )
    assert report['errors'][0]['error'] == 'state_corrupt_recovered'
    corrupt = list(tmp_path.glob('state.json.corrupt-*'))
    assert len(corrupt) == 1 and corrupt[0].read_text(encoding='utf-8') == '{not json'
    state = json.loads(state_path.read_text(encoding='utf-8'))
    assert state['pending_errors'][0]['error'] == 'state_corrupt_recovered'


def test_write_failure_state_records_attempt_and_keeps_ledger(tmp_path):
    """任务整体失败也要留痕：写 last_attempt_at/last_error，保留既有账本。"""
    state_path = tmp_path / 'state.json'
    state_path.write_text(json.dumps({
        'archive_files': {'2025-09': {'path': 'x', 'rows': 1, 'sha256': 'y'}},
        'deleted_rows_total': 7,
    }), encoding='utf-8')

    art.write_failure_state(RuntimeError('boom'), state_path)
    state = json.loads(state_path.read_text(encoding='utf-8'))
    assert state['last_error'] == 'RuntimeError: boom'
    assert 'last_attempt_at' in state
    assert 'last_success_at' not in state
    assert state['archive_files']['2025-09']['rows'] == 1
    assert state['deleted_rows_total'] == 7


def test_write_skip_state_records_reason(tmp_path):
    """因锁跳过也要留痕（评审 L-1）：否则只能等 7 天 staleness 且看不出原因。"""
    state_path = tmp_path / 'state.json'
    art.write_skip_state('lock_busy', state_path)
    state = json.loads(state_path.read_text(encoding='utf-8'))
    assert state['skip_reason'] == 'lock_busy'
    assert 'last_skipped_at' in state


def test_skip_state_preserves_sibling_fields(tmp_path):
    """因锁跳过只该写它自己那两个字段，其它字段（尤其 pending_errors）必须原样保留。

    ``write_skip_state`` 只在**别人持锁运行**时被调用：若它拿一份旧快照整体写回，
    持锁方刚清掉的错误会被「复活」（假 degraded），刚记下的错误会被静默清掉
    （健康转绿）。所以合并必须以**落盘前那一刻的磁盘状态**为底。
    变异验证：把合并改成 `merged = {**fields}` 后本测试失败。
    """
    state_path = tmp_path / 'state.json'
    existing = {
        'last_success_at': '2026-11-01T03:00:00+00:00',
        'archive_files': {'2025-10': {'path': 'b', 'rows': 2, 'sha256': 'y'}},
        'deleted_rows_total': 9,
        'pending_errors': [{'month': '2025-10', 'error': 'archive_incomplete'}],
        'last_error': 'OSError: disk full',
    }
    state_path.write_text(json.dumps(existing), encoding='utf-8')

    art.write_skip_state('lock_busy', state_path)

    state = json.loads(state_path.read_text(encoding='utf-8'))
    assert state['skip_reason'] == 'lock_busy' and 'last_skipped_at' in state
    assert state['last_success_at'] == existing['last_success_at']
    assert state['pending_errors'] == existing['pending_errors']   # 不许复活/清掉
    assert state['last_error'] == existing['last_error']
    assert state['deleted_rows_total'] == 9
    assert set(state['archive_files']) == {'2025-10'}


# ---------------------------------------------------------------------------
# 5. ARQ 入口：专用连接 + 锁 + 失败留痕
# ---------------------------------------------------------------------------
class _FakeConn:
    def __init__(self, lock_ok: bool = True, unlock_error: Exception | None = None):
        self.lock_ok = lock_ok
        self.unlock_error = unlock_error
        self.invalidated = False
        self.calls: list[str] = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append(sql)
        if 'pg_try_advisory_lock' in sql:
            return _Result([], scalar=self.lock_ok)
        if 'pg_advisory_unlock' in sql:
            if self.unlock_error:
                raise self.unlock_error
            return _Result([], scalar=True)
        return _Result([], scalar=True)

    async def rollback(self):
        self.calls.append('rollback')

    async def invalidate(self):
        # 解锁失败时任务会把连接丢掉（会话级锁随后端连接终止释放）
        self.invalidated = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeEngine:
    """每次 connect() 都发一条**新**连接：这样「锁和解锁是否同一条连接」可断言。

    早期替身对所有 connect() 返回同一个对象，等于替实现保证了 H-1 的核心
    前提——「锁挂在另一条连接上」这种回归在替身里根本表达不出来。
    """

    def __init__(self, lock_ok: bool = True, unlock_error: Exception | None = None):
        self.conns: list[_FakeConn] = []
        self._lock_ok = lock_ok
        self._unlock_error = unlock_error

    def connect(self):
        conn = _FakeConn(self._lock_ok, self._unlock_error)
        self.conns.append(conn)
        return conn


class _FakeSessionCM:
    """``AsyncSession(bind=..., join_transaction_mode=...)`` 的替身：记录构造参数。

    替身必须**看见**构造参数，否则「会话绑在哪条连接上」「是否显式接管事务」
    这两个 H-1/Blocker 的核心前提在单测层无法断言（复审 Medium-1）。
    """

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc):
        return False


def _patch_session(monkeypatch) -> dict:
    """把 AsyncSession 换成记录构造参数的替身，返回 {session: _FakeSessionCM}。"""
    seen: dict = {}

    def _factory(**kwargs):
        seen['session'] = _FakeSessionCM(**kwargs)
        return seen['session']

    monkeypatch.setattr(art, 'AsyncSession', _factory)
    return seen


async def test_task_holds_lock_on_dedicated_connection(monkeypatch, tmp_path):
    """锁必须跑在 engine.connect() 的专用连接上，且结束时在同一连接上释放。

    评审 H-1：会话级 advisory lock 跟 DBAPI 连接走，Session.commit() 会把连接
    归还池——锁若挂在会话上，第一批 commit 之后就可能换连接、解锁打空。
    真库探针已实测：池化写法 commit 后锁仍在 pg_locks 里（连接回池），在非持
    锁连接上 unlock 只回 false 不报错。本测试把这条不变式钉在单元层：
    **全程只允许出现一条连接，lock/unlock 都发生在它身上**，且会话必须绑在
    这条连接上、并显式 ``control_fully`` 接管事务（否则 commit 只是 flush，
    删除会在 finally 的 rollback 里被丢掉——复审 Blocker）。
    变异验证：把 try_lock 挪到另一条连接、或去掉 control_fully，本测试失败。
    """
    state_path = tmp_path / 'state.json'
    engine = _FakeEngine()
    monkeypatch.setattr(art, 'require_async_engine', lambda: engine)
    seen = _patch_session(monkeypatch)

    async def _run(db):
        return {'months': [], 'deleted_total': 0, 'analyzed': False, 'errors': []}

    monkeypatch.setattr(art, 'run_retention_once', _run)
    monkeypatch.setattr(art, 'STATE_PATH', state_path)

    await art.audit_retention_task({})
    assert len(engine.conns) == 1, '任务不应额外开连接（锁必须与解锁同连接）'
    session = seen['session']
    assert session.kwargs['bind'] is engine.conns[0], '会话必须绑在持锁连接上'
    assert session.kwargs.get('join_transaction_mode') == 'control_fully', (
        '取锁那条 SELECT 已 autobegin，不显式接管事务时 Session.commit() 只 flush')
    calls = engine.conns[0].calls
    assert any('pg_try_advisory_lock' in c for c in calls)
    assert any('pg_advisory_unlock' in c for c in calls)
    assert calls.index(next(c for c in calls if 'pg_try_advisory_lock' in c)) < (
        calls.index(next(c for c in calls if 'pg_advisory_unlock' in c)))


async def test_task_writes_failure_state_on_error(monkeypatch, tmp_path):
    """任务体抛错时先写 last_attempt_at/last_error，再释放锁并上抛。"""
    state_path = tmp_path / 'state.json'
    engine = _FakeEngine()
    monkeypatch.setattr(art, 'require_async_engine', lambda: engine)
    _patch_session(monkeypatch)

    async def _boom(db):
        raise RuntimeError('plan query failed')

    monkeypatch.setattr(art, 'run_retention_once', _boom)
    monkeypatch.setattr(art, 'STATE_PATH', state_path)

    with pytest.raises(RuntimeError, match='plan query failed'):
        await art.audit_retention_task({})

    state = json.loads(state_path.read_text(encoding='utf-8'))
    assert state['last_error'] == 'RuntimeError: plan query failed'
    assert 'last_success_at' not in state
    assert any('pg_advisory_unlock' in c for c in engine.conns[0].calls)


async def test_unlock_failure_discards_the_connection(monkeypatch, tmp_path):
    """解锁语句失败：连接必须被丢弃，否则会话级锁跟着回池、后续永远 lock_busy。

    ``pg_advisory_lock`` 是**会话级**锁，回池复用的连接仍持有它；本任务下次
    ``pg_try_advisory_lock`` 还会「重入成功」，而别的实例/手工补跑拿不到锁。
    ``conn.invalidate()`` 让后端连接终止，锁随后端一起释放。
    变异验证：去掉 invalidate() 调用后本测试失败。
    """
    state_path = tmp_path / 'state.json'
    engine = _FakeEngine(unlock_error=SQLAlchemyError('server closed the connection'))
    monkeypatch.setattr(art, 'require_async_engine', lambda: engine)
    _patch_session(monkeypatch)

    async def _run(db):
        return {'months': [], 'deleted_total': 0, 'analyzed': False, 'errors': []}

    monkeypatch.setattr(art, 'run_retention_once', _run)
    monkeypatch.setattr(art, 'STATE_PATH', state_path)

    report = await art.audit_retention_task({})
    assert report['deleted_total'] == 0          # 解锁失败不该让成功的一轮变失败
    assert engine.conns[0].invalidated is True


async def test_task_skips_and_records_when_lock_busy(monkeypatch, tmp_path):
    """拿不到锁：干净退出、不误写成功态，但要留下 last_skipped_at。"""
    state_path = tmp_path / 'state.json'
    engine = _FakeEngine(lock_ok=False)
    monkeypatch.setattr(art, 'require_async_engine', lambda: engine)
    _patch_session(monkeypatch)
    monkeypatch.setattr(art, 'STATE_PATH', state_path)

    result = await art.audit_retention_task({})
    assert result == {'skipped': 'lock_busy'}
    state = json.loads(state_path.read_text(encoding='utf-8'))
    assert state['skip_reason'] == 'lock_busy'
    assert 'last_success_at' not in state
    assert not any('pg_advisory_unlock' in c for c in engine.conns[0].calls)


# ---------------------------------------------------------------------------
# 6. 健康信号
# ---------------------------------------------------------------------------
def _write_signal_state(tmp_path, monkeypatch, **fields):
    path = tmp_path / 'state.json'
    path.write_text(json.dumps(fields), encoding='utf-8')
    monkeypatch.setattr(art, 'STATE_PATH', path)
    return path


def test_skip_state_keeps_corrupt_ledger_raw(tmp_path):
    """抢锁失败写 skip 状态时，绝不能把非法账本值「取大」成 0。

    跳过路径通常先于成功路径落盘；一旦在这里清零，成功路径就再看不到损坏，
    「另存 .corrupt-* + ledger_corrupt + 原值字段」三重留痕一个都不会发生。
    变异验证：把 _merge_state 的账本合并改回无条件 max(_as_int(...)) 后本测试失败。
    """
    state_path = tmp_path / 'state.json'
    state_path.write_text(json.dumps({
        'deleted_rows_total': '1,234', 'archive_files': {},
    }), encoding='utf-8')

    art.write_skip_state('lock_busy', state_path)

    state = json.loads(state_path.read_text(encoding='utf-8'))
    assert state['deleted_rows_total'] == '1,234'     # 原样保留，等成功路径处置
    assert state['skip_reason'] == 'lock_busy'


def test_signal_exposes_ledger_corrupt_marker(tmp_path, monkeypatch):
    """账本损坏痕迹要能在健康响应里看到（pending_errors 清空后也不消失）。"""
    _write_signal_state(
        tmp_path, monkeypatch,
        last_success_at=datetime.now(UTC).isoformat(),
        pending_errors=[],
        deleted_rows_total_corrupt={'value': '1,234', 'detected_at': '2026-11-01T00:00:00+00:00'},
    )
    sig = art.audit_retention_signal()
    assert sig['ok'] is True                      # 已知状态，不再重复降级
    assert sig['ledger_corrupt']['value'] == '1,234'


def test_signal_shape_is_identical_across_branches(tmp_path, monkeypatch):
    """五种分支必须返回**同一套键**——契约快照只能钉住一种结构。

    结构随运行状态变（禁用/误配/从未运行/停摆或损坏/正常）时：契约快照钉住哪个
    分支都只是碰运气（CI 上是「从未运行」，装了任务的机器上是「正常」），前端也
    只能按「字段可能不存在」写防御代码。CI 就是这么红过一次（health 契约漂移）。
    变异验证：让任一分支少返回一个键，本测试失败。
    """
    shapes: list[set[str]] = []
    state_path = tmp_path / 'state.json'
    monkeypatch.setattr(art, 'STATE_PATH', state_path)

    monkeypatch.setattr(settings, 'AUDIT_RETENTION_MONTHS', 0, raising=False)
    shapes.append(set(art.audit_retention_signal()))            # 禁用

    monkeypatch.setattr(settings, 'AUDIT_RETENTION_MONTHS', 3, raising=False)
    shapes.append(set(art.audit_retention_signal()))            # 低于法定下限

    monkeypatch.setattr(settings, 'AUDIT_RETENTION_MONTHS', 12, raising=False)
    shapes.append(set(art.audit_retention_signal()))            # 从未运行（文件不存在）

    state_path.write_text(json.dumps({
        'last_attempt_at': datetime.now(UTC).isoformat(),
        'last_error': 'RuntimeError: boom',
    }), encoding='utf-8')
    shapes.append(set(art.audit_retention_signal()))            # 跑过但从未成功

    state_path.write_text(json.dumps({
        'last_success_at': datetime.now(UTC).isoformat(),
        'retention_months': 12, 'deleted_rows_total': 5,
        'pending_errors': [],
    }), encoding='utf-8')
    shapes.append(set(art.audit_retention_signal()))            # 正常

    for idx, shape in enumerate(shapes[1:], start=2):
        assert shape == shapes[0], f'第 {idx} 个分支的键集与「禁用」分支不同：{shape ^ shapes[0]}'


def test_signal_ok_when_fresh(tmp_path, monkeypatch):
    _write_signal_state(tmp_path, monkeypatch,
                        last_success_at=datetime.now(UTC).isoformat(),
                        retention_months=12, deleted_rows_total=100,
                        archive_files={}, pending_errors=[])
    sig = art.audit_retention_signal()
    assert sig['ok'] is True
    assert sig['pending_error_count'] == 0


def test_signal_stale_after_threshold(tmp_path, monkeypatch):
    old = (datetime.now(UTC) - timedelta(days=art.STALE_DAYS + 1)).isoformat()
    _write_signal_state(tmp_path, monkeypatch, last_success_at=old, pending_errors=[])
    assert art.audit_retention_signal()['ok'] is False


def test_signal_not_ok_when_pending_errors(tmp_path, monkeypatch):
    """新鲜但有未处理错误 ⇒ ok=False。

    变异验证：从 ok 表达式里去掉 ``and not pending`` 后本测试失败。
    """
    _write_signal_state(tmp_path, monkeypatch,
                        last_success_at=datetime.now(UTC).isoformat(),
                        pending_errors=[{'month': '2025-10', 'error': 'archive_incomplete'}])
    sig = art.audit_retention_signal()
    assert sig['ok'] is False
    assert sig['pending_error_count'] == 1


def test_signal_missing_state_is_grace(tmp_path, monkeypatch):
    monkeypatch.setattr(art, 'STATE_PATH', tmp_path / 'absent.json')
    sig = art.audit_retention_signal()
    assert sig['ok'] is True and sig['note'] == 'not_yet_run'


def test_signal_corrupt_state_is_not_grace(tmp_path, monkeypatch):
    path = tmp_path / 'state.json'
    path.write_text('{not json', encoding='utf-8')
    monkeypatch.setattr(art, 'STATE_PATH', path)
    sig = art.audit_retention_signal()
    assert sig['ok'] is False and sig['note'] == 'state_unreadable'


def test_signal_bad_timestamp_is_not_grace(tmp_path, monkeypatch):
    """JSON 合法但 last_success_at 坏/缺失 ⇒ 也必须 ok=False（评审 M1）。"""
    path = tmp_path / 'state.json'
    path.write_text(json.dumps({'last_success_at': ''}), encoding='utf-8')
    monkeypatch.setattr(art, 'STATE_PATH', path)
    assert art.audit_retention_signal()['ok'] is False

    path.write_text(json.dumps({'last_success_at': 'not-a-time'}), encoding='utf-8')
    assert art.audit_retention_signal()['ok'] is False


def test_signal_naive_timestamp_is_interpreted_as_utc(tmp_path, monkeypatch):
    """naive 时间戳不能让函数抛错，也不能逃成 signal_error。"""
    naive = datetime.now(UTC).replace(tzinfo=None).isoformat()
    _write_signal_state(tmp_path, monkeypatch, last_success_at=naive, pending_errors=[])
    sig = art.audit_retention_signal()
    assert sig['ok'] is True and sig['age_days'] < 1


def test_signal_failed_run_uses_never_succeeded_note(tmp_path, monkeypatch):
    """只有 last_attempt_at、没有 last_success_at ⇒ ok=False 且 note 区分成因。

    评审 L-2：把「跑过但从未成功」报成 state_unreadable 会让运维去查文件损坏，
    而真正的问题在任务。
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
    assert sig['note'] == 'never_succeeded'
    assert sig['last_error'] == 'RuntimeError: boom'


def test_signal_disabled_when_months_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'AUDIT_RETENTION_MONTHS', 0, raising=False)
    monkeypatch.setattr(art, 'STATE_PATH', tmp_path / 'absent.json')
    sig = art.audit_retention_signal()
    assert sig['ok'] is True and sig['disabled'] is True


def test_signal_pending_errors_truncated(tmp_path, monkeypatch):
    _write_signal_state(tmp_path, monkeypatch,
                        last_success_at=datetime.now(UTC).isoformat(),
                        pending_errors=[{'month': f'2025-{i:02d}', 'error': 'x'}
                                        for i in range(1, 9)])
    sig = art.audit_retention_signal()
    assert len(sig['pending_errors']) == 5
    assert sig['pending_error_count'] == 8


# ---------------------------------------------------------------------------
# 7. 与 health 端点的接线
# ---------------------------------------------------------------------------
def test_status_resolution_maps_retention_to_degraded():
    """状态判定是对外可观测承诺，必须能被单测直接打（评审 M7）。"""
    from fastapi_app.core.health import _resolve_status

    assert _resolve_status(True, True, True) == 'healthy'
    assert _resolve_status(True, True, False) == 'degraded'
    assert _resolve_status(True, False, True) == 'degraded'
    assert _resolve_status(True, False, False) == 'degraded'
    assert _resolve_status(False, True, True) == 'unhealthy'


async def test_health_degrades_end_to_end(monkeypatch):
    """驱动 _build_fresh_health：保留治理不 ok 时 status 必须是 degraded。"""
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
