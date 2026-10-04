"""restore_legacy_json 回归测试（Legacy JSON v1.0 还原主链路）。

背景：该函数此前**零测试覆盖**，2026-10-04 的纯抽取重构（拆成 _disable_fk_constraints /
_clear_tables_for_restore / _restore_tables_from_json / _verify_restored_json 等）只靠
「AST 调用序列比对」确认等价。本文件把关键行为钉住，防止将来改动静默回归。

用真实模型表（role / pattern_maker）驱动，无需 patch Base；用记录型 FakeSession
捕获实际执行的 SQL，断言：清空顺序、upsert/do-nothing 分支、delete_failed→partial、
verify 失败→_verification_failed、superuser→session_replication_role 切换。
"""
import pytest
from sqlalchemy.exc import SQLAlchemyError

from fastapi_app.services.backup import json_backup
from fastapi_app.services.backup import verify as verify_pkg
from fastapi_app.shared_models import Base


class _Result:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def all(self):
        return self._rows

    def fetchall(self):
        return self._rows

    def scalar(self):
        return self._scalar


class _Nested:
    def __init__(self):
        self.committed = False
        self.rolled_back = False

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


class FakeSession:
    """记录所有 execute 的 SQL，模拟 begin_nested/flush/rollback。"""

    def __init__(self, superuser=False, delete_fail_tables=()):
        self.executed: list[str] = []          # 按序记录 SQL 文本
        self.params: list = []
        self.superuser = superuser
        self.delete_fail_tables = set(delete_fail_tables)
        self.replica_roles: list[str] = []      # 记录 SET session_replication_role 的值
        self.flushed = False
        self.rolled_back = False

    @staticmethod
    def _sql(stmt) -> str:
        return getattr(stmt, 'text', None) or str(stmt)

    async def execute(self, stmt, params=None):
        sql = self._sql(stmt)
        self.executed.append(sql)
        self.params.append(params)
        if 'usesuper' in sql:
            return _Result(scalar=self.superuser)
        if sql.startswith('SET session_replication_role'):
            self.replica_roles.append(sql)
            return _Result()
        if sql.startswith('DELETE FROM'):
            tname = sql.split('DELETE FROM ', 1)[1].strip().strip('"')
            if tname in self.delete_fail_tables:
                raise SQLAlchemyError(f'模拟外键约束失败: {tname}')
        return _Result()

    async def begin_nested(self):
        return _Nested()

    async def flush(self):
        self.flushed = True

    async def rollback(self):
        self.rolled_back = True


def _backup_data():
    return {
        'tables': {
            'role': {'columns': ['id', 'name'], 'rows': [{'id': 1, 'name': 'admin'}]},
            'pattern_maker': {'columns': ['id'], 'rows': [{'id': 7}]},
        },
        'schema_snapshot': None,
    }


def _patch_verify(monkeypatch, result):
    async def _fake(db, manifest_tables, manifest_fingerprints=None, manifest_schema=None):
        return result
    monkeypatch.setattr(verify_pkg, 'verify_restore', _fake)


@pytest.mark.asyncio
async def test_clears_then_upserts_with_correct_conflict_clauses(monkeypatch):
    _patch_verify(monkeypatch, {'overall_pass': True})
    db = FakeSession()

    result = await json_backup.restore_legacy_json(_backup_data(), db)

    # 1) 先清空：DELETE 覆盖两张表，且顺序 = 模型依赖序的逆序（子表先清）
    sorted_names = [str(t.name) for t in Base.metadata.sorted_tables]
    expected_delete_order = [n for n in reversed(sorted_names) if n in _backup_data()['tables']]
    actual_delete_order = [s.split('DELETE FROM ', 1)[1].strip().strip('"')
                           for s in db.executed if s.startswith('DELETE FROM')]
    assert actual_delete_order == expected_delete_order

    # 2) 逐表 INSERT：有非主键列 → ON CONFLICT DO UPDATE；仅主键 → DO NOTHING
    inserts = [s for s in db.executed if s.startswith('INSERT INTO')]
    assert any('ON CONFLICT (id) DO UPDATE SET "name" = EXCLUDED."name"' in s for s in inserts)
    assert any('ON CONFLICT DO NOTHING' in s for s in inserts)

    assert result['total_inserted'] == 2
    assert result['results']['role'] == {'status': 'ok', 'inserted': 1}
    assert result['results']['pattern_maker'] == {'status': 'ok', 'inserted': 1}
    assert result['errors'] == []
    assert result['database']['status'] == 'ok'
    assert db.flushed is True
    assert db.rolled_back is False


@pytest.mark.asyncio
async def test_delete_failure_is_reported_as_merged_restore(monkeypatch):
    _patch_verify(monkeypatch, {'overall_pass': True})
    db = FakeSession(delete_fail_tables={'role'})

    result = await json_backup.restore_legacy_json(_backup_data(), db)

    # 清空失败的表必须显式进 errors（合并语义，不得静默）→ 整体 partial
    assert result['database']['status'] == 'partial'
    assert any('role' in e and '合并恢复' in e for e in result['errors'])
    # 清空失败不阻断该表继续 upsert
    assert result['results']['role']['status'] == 'ok'


@pytest.mark.asyncio
async def test_verification_failure_sets_flag(monkeypatch):
    _patch_verify(monkeypatch, {'overall_pass': False, 'mismatches': ['role']})
    db = FakeSession()

    result = await json_backup.restore_legacy_json(_backup_data(), db)

    assert result['_verification_failed'] is True
    assert result['verification']['overall_pass'] is False


@pytest.mark.asyncio
async def test_superuser_toggles_session_replication_role(monkeypatch):
    _patch_verify(monkeypatch, {'overall_pass': True})
    db = FakeSession(superuser=True)

    await json_backup.restore_legacy_json(_backup_data(), db)

    assert any("'replica'" in s for s in db.replica_roles)
    assert any("'origin'" in s for s in db.replica_roles)
