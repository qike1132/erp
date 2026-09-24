"""M6 备份中心测试（2026-08-23 对标审核整改第二批）

覆盖:
1. P1-2 表级选择性备份:范围校验(互斥/白名单/归一化)
2. P1-3 六边形接线:还原内核唯一性源码守卫
3. P1-4 DR 演练例行化:task_type 映射 + 迁移 037 种子
4. P2:download-by-name 端点源码守卫 + ValidationCache Redis 降级语义

与既有里程碑测试同款纪律:独立运行,不依赖 client fixture。
"""
from pathlib import Path

import pytest

from fastapi_app.services.backup import schedule_service
from fastapi_app.services.backup.exceptions import BackupError
from fastapi_app.services.backup.orchestration.core import resolve_backup_table_scope

# ===========================================================================
# 1. P1-2 表级备份范围
# ===========================================================================

class TestResolveBackupTableScope:
    def test_no_scope_returns_none_none(self):
        assert resolve_backup_table_scope(None, None) == (None, None)
        assert resolve_backup_table_scope([], []) == (None, None)

    def test_include_and_exclude_mutually_exclusive(self):
        with pytest.raises(BackupError):
            resolve_backup_table_scope(['users'], ['orders'])

    def test_unknown_table_rejected(self):
        with pytest.raises(BackupError, match='未知的表名'):
            resolve_backup_table_scope(['no_such_table_xyz'], None)
        with pytest.raises(BackupError, match='未知的表名'):
            resolve_backup_table_scope(None, ['no_such_table_xyz'])

    def test_valid_include_normalizes_to_set(self):
        from fastapi_app.shared_models import Base
        some_table = str(Base.metadata.sorted_tables[0].name)
        include, exclude = resolve_backup_table_scope([some_table, some_table], None)
        assert include == {some_table}
        assert exclude is None

    def test_valid_exclude_normalizes_to_set(self):
        from fastapi_app.shared_models import Base
        some_table = str(Base.metadata.sorted_tables[0].name)
        include, exclude = resolve_backup_table_scope(None, [some_table])
        assert include is None
        assert exclude == {some_table}


class TestTableScopePlumbing:
    def test_actions_endpoint_passes_tables(self):
        src = Path('fastapi_app/api/v1/endpoints/backup/actions.py').read_text(encoding='utf-8')
        assert 'tables=payload.tables' in src
        assert 'exclude_tables=payload.exclude_tables' in src

    def test_partial_backup_uses_json_path(self):
        """表级备份固定 JSON 路径（还原按表 upsert，不整库重建）。"""
        src = Path('fastapi_app/services/backup/orchestration/core.py').read_text(encoding='utf-8')
        assert 'partial' in src and 'tables_scope' in src
        assert "'type': 'partial' if partial else 'full'" in src

    def test_json_export_filters_tables(self):
        src = Path('fastapi_app/services/backup/json_backup.py').read_text(encoding='utf-8')
        assert 'include_set is not None and name not in include_set' in src


# ===========================================================================
# 2. P1-3 六边形接线守卫
# ===========================================================================

class TestHexagonalWiring:
    def test_restore_from_zip_uses_orchestrator_kernel(self):
        src = Path('fastapi_app/services/backup/restore.py').read_text(encoding='utf-8')
        assert 'DatabaseRestoreOrchestrator(' in src, 'restore_from_zip 必须经内核编排'

    def test_restore_module_no_longer_duplicates_db_restore(self):
        """解密/校验/策略还原逻辑不再在 restore.py 重复实现。"""
        src = Path('fastapi_app/services/backup/restore.py').read_text(encoding='utf-8')
        assert 'restore_database_via_psql' not in src
        assert 'restore_database_from_json' not in src

    def test_noop_adapters_exist_for_endpoint_owned_duties(self):
        src = Path('fastapi_app/services/backup/adapters.py').read_text(encoding='utf-8')
        assert 'NoOpAdvisoryLockAdapter' in src
        assert 'NoOpSafetyBackupAdapter' in src


# ===========================================================================
# 3. P1-4 DR 演练例行化
# ===========================================================================

class TestDisasterRecoverySchedule:
    def test_task_type_mapping_registered(self):
        assert schedule_service.TASK_TYPE_TO_FUNC.get('disaster_recovery_test') == 'disaster_recovery_test_task'

    def test_worker_registers_dr_task(self):
        src = Path('fastapi_app/core/arq_app.py').read_text(encoding='utf-8')
        assert 'disaster_recovery_test_task' in src

    def test_migration_037_seeds_monthly_dr(self):
        p = Path('migrations/versions/pg_standalone_037_backup_dr_monthly.py')
        assert p.is_file(), '迁移 037 必须存在'
        src = p.read_text(encoding='utf-8')
        assert "'disaster_recovery_test', '30 3 1 * *'" in src.replace('"', "'"), '种子须为每月 1 日 03:30'
        assert '月度灾备恢复演练' in src
        # 对称 downgrade
        assert "DELETE FROM backup_schedule WHERE name = '月度灾备恢复演练'" in src.replace('"', "'")


# ===========================================================================
# 4. P2 项
# ===========================================================================

class TestDownloadByNameGuard:
    def test_download_endpoint_with_audit(self):
        src = Path('fastapi_app/api/v1/endpoints/backup/export.py').read_text(encoding='utf-8')
        assert "'/download/{filename}'" in src
        assert 'download_server_backup' in src
        # 高敏读操作必须走 EXPORT 审计
        assert src.index('/download/{filename}') < src.index("format='file'")


class TestValidationCacheRedis:
    @pytest.mark.asyncio
    async def test_get_returns_none_when_redis_unavailable(self, monkeypatch):
        from fastapi_app.api.v1.endpoints.backup import validation as validation_mod

        async def _no_redis():
            return None

        monkeypatch.setattr('fastapi_app.core.backup_progress._get_redis', _no_redis)
        assert await validation_mod._validation_cache.get('k') is None
        # set 为 no-op，不抛异常
        await validation_mod._validation_cache.set('k', {'a': 1})

    @pytest.mark.asyncio
    async def test_roundtrip_via_fake_redis(self, monkeypatch):
        from fastapi_app.api.v1.endpoints.backup import validation as validation_mod

        class _FakeRedis:
            def __init__(self):
                self.d = {}

            async def get(self, k):
                return self.d.get(k)

            async def set(self, k, v, ex=None):
                self.d[k] = v

        fake = _FakeRedis()

        async def _get():
            return fake

        monkeypatch.setattr('fastapi_app.core.backup_progress._get_redis', _get)
        await validation_mod._validation_cache.set('k1', {'ok': True})
        assert await validation_mod._validation_cache.get('k1') == {'ok': True}
        assert await validation_mod._validation_cache.get('missing') is None
