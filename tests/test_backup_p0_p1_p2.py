"""P0/P1/P2 备份修复单元测试

覆盖：
- P0: get_merged_backup_records — 文件系统为基准合并数据库记录
- P1: sync_backup_records — 启动时双向同步（补录/清理孤立/修正僵尸）
- P2: write_backup_record — 失败累计计数 + 每 3 次告警

所有测试用 mock 隔离文件系统与数据库依赖，不依赖真实环境。
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from fastapi_app.services.backup.records import (
    sync_backup_records,
    write_backup_record,
)
from fastapi_app.services.backup.verify.query_service import get_merged_backup_records

# ============================================================
# 辅助构造函数
# ============================================================

def _make_db_record(**kwargs) -> MagicMock:
    """构造一个具备所有 BackupRecord 字段的 mock 对象。

    默认值代表一条成功的手动全量备份记录；测试可通过 kwargs 覆盖任意字段。
    """
    rec = MagicMock()
    defaults = {
        'id': 1,
        'type': 'full',
        'trigger_type': 'manual',
        'filename': 'erp_backup_20240101_120000.zip',
        'size': 1024,
        'table_count': 50,
        'total_rows': 1000,
        'operator': 'admin',
        'remark': 'manual backup',
        'status': 'success',
        'error_message': None,
        'duration_seconds': 120.0,
        'ip_address': '127.0.0.1',
        'user_agent': 'test-ua',
        'parent_record_id': None,
        'created_at': datetime(2024, 1, 1, 12, 0, 0),
        'updated_at': datetime(2024, 1, 1, 12, 0, 5),
        'encrypted': False,
    }
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(rec, k, v)
    return rec


def _make_execute_result(records: list) -> MagicMock:
    """构造 db.execute() 的返回值，使 .scalars().all() 返回 records。"""
    result = MagicMock()
    result.scalars.return_value.all.return_value = records
    return result


def _make_db_context_mock(db: AsyncMock) -> MagicMock:
    """构造 get_async_db_context 的 mock，async with ... as db 返回给定 db。"""
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=ctx)


def _make_sync_db_mock(records: list) -> AsyncMock:
    """构造 sync_backup_records 使用的 db 会话 mock。

    - execute() 返回包含 records 的结果（删除孤立的 execute 返回值不被使用）
    - add/flush/rollback 均为无副作用 mock
    """
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock(return_value=_make_execute_result(records))
    return db


# ============================================================
# P0: get_merged_backup_records 合并查询
# ============================================================

class TestGetMergedBackupRecords:
    """P0: 以文件系统扫描为基准合并数据库记录"""

    @pytest.mark.asyncio
    async def test_fs_and_db_match_returns_db_source(self):
        """场景1: 文件系统有文件、DB有匹配记录 → source='db'，含数据库专属字段"""
        fs_entries = [
            {'filename': 'erp_backup_20240101_120000.zip', 'size': 1024},
        ]
        db_rec = _make_db_record(
            operator='admin',
            status='success',
            duration_seconds=120.0,
            ip_address='10.0.0.1',
            error_message=None,
        )

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_execute_result([db_rec]))

        with patch('fastapi_app.services.backup.list_backup_files', return_value=fs_entries):
            records, total = await get_merged_backup_records(db, page=1, page_size=10)

        assert total == 1
        assert len(records) == 1
        rec = records[0]
        # 来源标记为 db
        assert rec['source'] == 'db'
        # 包含数据库专属字段
        assert rec['operator'] == 'admin'
        assert rec['status'] == 'success'
        assert rec['duration_seconds'] == 120.0
        assert rec['ip_address'] == '10.0.0.1'
        assert rec['id'] == 1
        assert rec['error_message'] is None

    @pytest.mark.asyncio
    async def test_fs_only_returns_fs_source_with_inferred_fields(self):
        """场景2: 文件系统有文件、DB无记录 → source='fs'，从文件名推断 type/trigger_type"""
        fs_entries = [
            {'filename': 'erp_incremental_20240101_120000.zip', 'size': 100},
            {'filename': 'erp_auto_20240102_120000.zip', 'size': 200},
            {'filename': 'erp_backup_20240103_120000.zip', 'size': 300},
        ]

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_execute_result([]))

        with patch('fastapi_app.services.backup.list_backup_files', return_value=fs_entries):
            records, total = await get_merged_backup_records(db, page=1, page_size=10)

        assert total == 3
        assert all(r['source'] == 'fs' for r in records)

        # 增量备份：erp_incremental_ → type=incremental, trigger=manual
        inc = next(r for r in records if 'incremental' in r['filename'])
        assert inc['type'] == 'incremental'
        assert inc['trigger_type'] == 'manual'
        assert inc['status'] == 'success'  # fs 视为成功
        assert inc['id'] is None

        # 自动备份：erp_auto_ → type=full, trigger=auto
        auto = next(r for r in records if r['filename'].startswith('erp_auto_'))
        assert auto['type'] == 'full'
        assert auto['trigger_type'] == 'auto'

        # 手动全量：erp_backup_ → type=full, trigger=manual
        manual = next(r for r in records if r['filename'].startswith('erp_backup_'))
        assert manual['type'] == 'full'
        assert manual['trigger_type'] == 'manual'

    @pytest.mark.asyncio
    async def test_db_only_without_file_is_excluded(self):
        """场景3: DB有记录但文件系统无文件 → 不返回（以文件系统为基准）"""
        fs_entries = []  # 文件系统无文件

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_execute_result([]))

        with patch('fastapi_app.services.backup.list_backup_files', return_value=fs_entries):
            records, total = await get_merged_backup_records(db, page=1, page_size=10)

        assert total == 0
        assert records == []
        # filenames 为空时不应查询数据库
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_pagination_correct(self):
        """场景4: 分页正确 — page=1,page_size=2 返回前2条，total 为全部数量"""
        fs_entries = [
            {
                'filename': f'erp_backup_2024010{i}_120000.zip',
                'size': 100 * i,
                'exported_at': f'2024-01-0{i} 12:00:00',
            }
            for i in range(1, 5)  # 4 个文件
        ]

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_execute_result([]))

        with patch('fastapi_app.services.backup.list_backup_files', return_value=fs_entries):
            page1, total = await get_merged_backup_records(db, page=1, page_size=2)
            page2, _ = await get_merged_backup_records(db, page=2, page_size=2)

        # total 为全部数量
        assert total == 4
        # 第1页 2 条
        assert len(page1) == 2
        # 第2页 2 条
        assert len(page2) == 2
        # 倒序：第1页应为最新两个（01-04, 01-03）
        assert page1[0]['filename'] == 'erp_backup_20240104_120000.zip'
        assert page1[1]['filename'] == 'erp_backup_20240103_120000.zip'
        # 第2页应为较旧两个（01-02, 01-01）
        assert page2[0]['filename'] == 'erp_backup_20240102_120000.zip'
        assert page2[1]['filename'] == 'erp_backup_20240101_120000.zip'
        # 两页不重叠
        page1_names = {r['filename'] for r in page1}
        page2_names = {r['filename'] for r in page2}
        assert page1_names.isdisjoint(page2_names)

    @pytest.mark.asyncio
    async def test_sort_desc_by_created_at(self):
        """场景5: 排序正确 — 按 created_at 倒序"""
        # 故意乱序输入
        fs_entries = [
            {'filename': 'erp_backup_20240101_120000.zip', 'exported_at': '2024-01-01 12:00:00'},
            {'filename': 'erp_backup_20240103_120000.zip', 'exported_at': '2024-01-03 12:00:00'},
            {'filename': 'erp_backup_20240102_120000.zip', 'exported_at': '2024-01-02 12:00:00'},
        ]

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_execute_result([]))

        with patch('fastapi_app.services.backup.list_backup_files', return_value=fs_entries):
            records, total = await get_merged_backup_records(db, page=1, page_size=10)

        assert total == 3
        # 倒序：03 → 02 → 01
        assert records[0]['filename'] == 'erp_backup_20240103_120000.zip'
        assert records[1]['filename'] == 'erp_backup_20240102_120000.zip'
        assert records[2]['filename'] == 'erp_backup_20240101_120000.zip'
        # created_at 单调递减
        created_ats = [r['created_at'] for r in records]
        assert created_ats == sorted(created_ats, reverse=True)

    @pytest.mark.asyncio
    async def test_db_fields_merge_with_fs_fallback(self):
        """边界: DB 字段为 None 时回退到文件系统信息（size/table_count）"""
        fs_entries = [
            {'filename': 'erp_backup_20240101_120000.zip', 'size': 2048, 'table_count': 30},
        ]
        # DB 记录的 size/table_count 为 None，应回退到 fs 值
        db_rec = _make_db_record(size=None, table_count=None)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_execute_result([db_rec]))

        with patch('fastapi_app.services.backup.list_backup_files', return_value=fs_entries):
            records, total = await get_merged_backup_records(db, page=1, page_size=10)

        assert total == 1
        assert records[0]['size'] == 2048
        assert records[0]['table_count'] == 30
        assert records[0]['source'] == 'db'


# ============================================================
# P1: sync_backup_records 双向同步
# ============================================================

class TestSyncBackupRecords:
    """P1: 启动时双向同步文件系统与数据库备份记录"""

    @pytest.mark.asyncio
    async def test_backfill_missing_records(self):
        """场景1: 补录 — fs有3个文件，DB有1条记录 → backfilled=2"""
        from fastapi_app.services.backup import records as records_mod

        fs_files = [
            {'filename': 'erp_backup_20240101_120000.zip', 'size': 100,
             'exported_at': '2024-01-01 12:00:00'},
            {'filename': 'erp_backup_20240102_120000.zip', 'size': 200,
             'exported_at': '2024-01-02 12:00:00'},
            {'filename': 'erp_backup_20240103_120000.zip', 'size': 300,
             'exported_at': '2024-01-03 12:00:00'},
        ]
        # DB 只有第1个文件的记录
        existing = MagicMock()
        existing.filename = 'erp_backup_20240101_120000.zip'
        existing.status = 'success'

        db = _make_sync_db_mock([existing])

        with patch.object(records_mod, 'list_backup_files', return_value=fs_files):
            with patch('fastapi_app.core.database.get_async_db_context',
                       _make_db_context_mock(db)):
                result = await sync_backup_records()

        assert result['backfilled'] == 2
        assert result['orphaned'] == 0
        assert result['zombie_fixed'] == 0
        assert result['errors'] == []
        # 补录应调用 db.add 两次 + flush 两次
        assert db.add.call_count == 2

    @pytest.mark.asyncio
    async def test_cleanup_orphaned_records(self):
        """场景2: 清理孤立 — DB有2条记录，fs只有1个文件 → orphaned=1"""
        from fastapi_app.services.backup import records as records_mod

        fs_files = [
            {'filename': 'erp_backup_20240101_120000.zip', 'size': 100},
        ]
        # DB 有2条记录，其中1条对应文件不存在
        r1 = MagicMock()
        r1.filename = 'erp_backup_20240101_120000.zip'  # 文件存在
        r1.status = 'success'
        r2 = MagicMock()
        r2.filename = 'erp_backup_20240102_120000.zip'  # 文件不存在（孤立）
        r2.status = 'success'

        db = _make_sync_db_mock([r1, r2])

        with patch.object(records_mod, 'list_backup_files', return_value=fs_files):
            with patch('fastapi_app.core.database.get_async_db_context',
                       _make_db_context_mock(db)):
                result = await sync_backup_records()

        assert result['backfilled'] == 0
        assert result['orphaned'] == 1
        assert result['zombie_fixed'] == 0
        assert result['errors'] == []

    @pytest.mark.asyncio
    async def test_fix_zombie_running_status(self):
        """场景3: 修正僵尸 — status='running' 且文件存在 → status='unknown'

        S4 起不再把「文件存在」当作「内容完整」：中断的备份同样会留下文件，
        旧实现把它洗成 success，导致缺表的备份在审计里显示为成功。
        """
        from fastapi_app.services.backup import records as records_mod

        fs_files = [
            {'filename': 'erp_backup_20240101_120000.zip', 'size': 100},
        ]
        # DB 有1条 running 状态记录，对应文件存在
        zombie = MagicMock()
        zombie.filename = 'erp_backup_20240101_120000.zip'
        zombie.status = 'running'

        db = _make_sync_db_mock([zombie])

        with patch.object(records_mod, 'list_backup_files', return_value=fs_files):
            with patch('fastapi_app.core.database.get_async_db_context',
                       _make_db_context_mock(db)):
                result = await sync_backup_records()

        assert result['backfilled'] == 0
        assert result['orphaned'] == 0
        assert result['zombie_fixed'] == 1
        assert result['errors'] == []
        # S4：状态修正为 unknown（文件存在但内容完整性未经校验），不是 success
        assert zombie.status == 'unknown'
        assert '内容完整性未经校验' in zombie.remark

    @pytest.mark.asyncio
    async def test_idempotent_second_call_no_change(self):
        """场景4: 幂等性 — 第二次调用 backfilled=0, orphaned=0, zombie_fixed=0"""
        from fastapi_app.services.backup import records as records_mod

        fs_files = [
            {'filename': 'erp_backup_20240101_120000.zip', 'size': 100,
             'exported_at': '2024-01-01 12:00:00'},
            {'filename': 'erp_backup_20240102_120000.zip', 'size': 200,
             'exported_at': '2024-01-02 12:00:00'},
        ]

        # 第一次调用：DB 只有1条记录，需补录1条
        r1 = MagicMock()
        r1.filename = 'erp_backup_20240101_120000.zip'
        r1.status = 'success'
        db_first = _make_sync_db_mock([r1])

        with patch.object(records_mod, 'list_backup_files', return_value=fs_files):
            with patch('fastapi_app.core.database.get_async_db_context',
                       _make_db_context_mock(db_first)):
                first_result = await sync_backup_records()

        # 第一次应补录1条
        assert first_result['backfilled'] == 1

        # 第二次调用：DB 已包含全部记录（模拟第一次补录后的状态）
        r2 = MagicMock()
        r2.filename = 'erp_backup_20240102_120000.zip'
        r2.status = 'success'
        db_second = _make_sync_db_mock([r1, r2])

        with patch.object(records_mod, 'list_backup_files', return_value=fs_files):
            with patch('fastapi_app.core.database.get_async_db_context',
                       _make_db_context_mock(db_second)):
                second_result = await sync_backup_records()

        # 第二次无任何变更
        assert second_result['backfilled'] == 0
        assert second_result['orphaned'] == 0
        assert second_result['zombie_fixed'] == 0
        assert second_result['errors'] == []

    @pytest.mark.asyncio
    async def test_list_backup_files_error_tolerated(self):
        """场景5: 错误容错 — list_backup_files 抛异常时返回 errors 不崩溃"""
        from fastapi_app.services.backup import records as records_mod

        with patch.object(records_mod, 'list_backup_files',
                          side_effect=OSError('disk read error')):
            with patch('fastapi_app.core.database.get_async_db_context',
                       _make_db_context_mock(AsyncMock())):
                result = await sync_backup_records()

        assert result['backfilled'] == 0
        assert result['orphaned'] == 0
        assert result['zombie_fixed'] == 0
        assert len(result['errors']) == 1
        assert 'list_backup_files' in result['errors'][0]

    @pytest.mark.asyncio
    async def test_db_query_error_tolerated(self):
        """边界: 数据库查询失败时返回 errors 不崩溃"""
        from fastapi_app.services.backup import records as records_mod

        fs_files = [{'filename': 'erp_backup_20240101_120000.zip', 'size': 100}]

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=SQLAlchemyError('connection lost'))

        with patch.object(records_mod, 'list_backup_files', return_value=fs_files):
            with patch('fastapi_app.core.database.get_async_db_context',
                       _make_db_context_mock(db)):
                result = await sync_backup_records()

        assert result['backfilled'] == 0
        assert result['orphaned'] == 0
        assert result['zombie_fixed'] == 0
        assert len(result['errors']) >= 1

    @pytest.mark.asyncio
    async def test_backfill_flush_error_recorded(self):
        """边界: 补录时 db.flush 失败 → 记录 errors，继续后续同步"""
        from fastapi_app.services.backup import records as records_mod

        fs_files = [
            {'filename': 'erp_backup_20240101_120000.zip', 'size': 100,
             'exported_at': '2024-01-01 12:00:00'},
        ]
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock(side_effect=SQLAlchemyError('flush failed'))
        db.rollback = AsyncMock()
        db.execute = AsyncMock(return_value=_make_execute_result([]))

        with patch.object(records_mod, 'list_backup_files', return_value=fs_files):
            with patch('fastapi_app.core.database.get_async_db_context',
                       _make_db_context_mock(db)):
                result = await sync_backup_records()

        assert result['backfilled'] == 0
        assert len(result['errors']) == 1
        assert '补录' in result['errors'][0]

    @pytest.mark.asyncio
    async def test_cleanup_orphan_execute_error_recorded(self):
        """边界: 清理孤立时 db.execute 失败 → 记录 errors"""
        from fastapi_app.services.backup import records as records_mod

        fs_files = [
            {'filename': 'erp_backup_20240101_120000.zip', 'size': 100},
        ]
        orphan = MagicMock()
        orphan.filename = 'erp_backup_20240102_120000.zip'  # 不在 fs
        orphan.status = 'success'
        orphan.id = 5

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.rollback = AsyncMock()
        # 第一次 execute（查询）成功；第二次（删除孤立）抛异常
        db.execute = AsyncMock(side_effect=[
            _make_execute_result([orphan]),
            SQLAlchemyError('delete failed'),
        ])

        with patch.object(records_mod, 'list_backup_files', return_value=fs_files):
            with patch('fastapi_app.core.database.get_async_db_context',
                       _make_db_context_mock(db)):
                result = await sync_backup_records()

        assert result['orphaned'] == 0
        assert len(result['errors']) == 1
        assert '清理孤立' in result['errors'][0]

    @pytest.mark.asyncio
    async def test_fix_zombie_flush_error_recorded(self):
        """边界: 修正僵尸时 db.flush 失败 → 记录 errors"""
        from fastapi_app.services.backup import records as records_mod

        fs_files = [
            {'filename': 'erp_backup_20240101_120000.zip', 'size': 100},
        ]
        zombie = MagicMock()
        zombie.filename = 'erp_backup_20240101_120000.zip'
        zombie.status = 'running'
        zombie.id = 1

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock(side_effect=SQLAlchemyError('flush failed'))
        db.rollback = AsyncMock()
        db.execute = AsyncMock(return_value=_make_execute_result([zombie]))

        with patch.object(records_mod, 'list_backup_files', return_value=fs_files):
            with patch('fastapi_app.core.database.get_async_db_context',
                       _make_db_context_mock(db)):
                result = await sync_backup_records()

        assert result['zombie_fixed'] == 0
        assert len(result['errors']) == 1
        assert '修正僵尸' in result['errors'][0]

    @pytest.mark.asyncio
    async def test_backfill_falls_back_to_filename_timestamp(self):
        """边界: exported_at 无效时回退到文件名时间戳解析"""
        from fastapi_app.services.backup import records as records_mod

        fs_files = [
            {'filename': 'erp_backup_20240101_120000.zip', 'size': 100,
             'exported_at': 'invalid-date'},
        ]
        db = _make_sync_db_mock([])

        with patch.object(records_mod, 'list_backup_files', return_value=fs_files):
            with patch('fastapi_app.core.database.get_async_db_context',
                       _make_db_context_mock(db)):
                result = await sync_backup_records()

        assert result['backfilled'] == 1
        # 验证补录的记录 created_at 来自文件名时间戳
        added_record = db.add.call_args[0][0]
        assert added_record.created_at == datetime(2024, 1, 1, 12, 0, 0)


# ============================================================
# P2: write_backup_record 失败告警逻辑
# ============================================================

class TestWriteBackupRecordAlert:
    """P2: write_backup_record 失败累计计数 + 每 3 次告警"""

    @pytest.fixture(autouse=True)
    def _reset_fail_count(self):
        """每个测试前重置模块级失败计数器，避免跨测试污染"""
        from fastapi_app.services.backup import records as records_mod
        records_mod._record_write_fail_count = 0
        yield
        records_mod._record_write_fail_count = 0

    @pytest.mark.asyncio
    async def test_single_failure_no_alert(self):
        """场景1: 单次失败不告警（计数=1，不满足%3==0）"""
        from fastapi_app.services.backup import records as records_mod

        db = AsyncMock()
        db.flush = AsyncMock(side_effect=SQLAlchemyError('flush failed'))
        db.add = MagicMock()

        mock_alert = MagicMock()
        mock_alert.send_alert = AsyncMock()
        mock_loop = MagicMock()

        with patch('fastapi_app.services.backup.metrics.alert_service.alert_service',
                   mock_alert), \
             patch('asyncio.get_running_loop', return_value=mock_loop):
            await write_backup_record(
                db=db, record_type='full', filename='erp_backup_test.zip',
                status='success',
            )

        # 计数=1，不触发告警
        assert records_mod._record_write_fail_count == 1
        mock_loop.create_task.assert_not_called()
        mock_alert.send_alert.assert_not_called()

    @pytest.mark.asyncio
    async def test_three_failures_trigger_alert(self):
        """场景2: 连续3次失败，第3次触发 alert_service.send_alert"""
        from fastapi_app.services.backup import records as records_mod

        db = AsyncMock()
        db.flush = AsyncMock(side_effect=SQLAlchemyError('flush failed'))
        db.add = MagicMock()

        mock_alert = MagicMock()
        mock_alert.send_alert = AsyncMock()
        mock_loop = MagicMock()

        with patch('fastapi_app.services.backup.metrics.alert_service.alert_service',
                   mock_alert), \
             patch('asyncio.get_running_loop', return_value=mock_loop):
            for _ in range(3):
                await write_backup_record(
                    db=db, record_type='full', filename='erp_backup_test.zip',
                    status='success',
                )

        # 计数=3
        assert records_mod._record_write_fail_count == 3
        # 第3次失败触发告警，create_task 调用 1 次
        assert mock_loop.create_task.call_count == 1
        # send_alert 被调用 1 次
        mock_alert.send_alert.assert_called_once()
        # 验证告警参数
        call_kwargs = mock_alert.send_alert.call_args.kwargs
        assert call_kwargs['task_name'] == 'backup_record_write'
        assert call_kwargs['task_type'] == 'backup'
        assert call_kwargs['severity'] == 'error'
        assert '连续失败 3 次' in call_kwargs['error']
        # 清理未 await 的 coroutine 避免 warning
        coro = mock_loop.create_task.call_args[0][0]
        coro.close()

    @pytest.mark.asyncio
    async def test_alert_failure_does_not_propagate(self):
        """场景3: alert_service.send_alert 自身异常不影响主流程"""
        from fastapi_app.services.backup import records as records_mod

        db = AsyncMock()
        db.flush = AsyncMock(side_effect=SQLAlchemyError('flush failed'))
        db.add = MagicMock()

        mock_alert = MagicMock()
        mock_alert.send_alert = AsyncMock()
        # create_task 抛异常模拟告警调度失败
        mock_loop = MagicMock()
        mock_loop.create_task = MagicMock(side_effect=RuntimeError('loop closed'))

        with patch('fastapi_app.services.backup.metrics.alert_service.alert_service',
                   mock_alert), \
             patch('asyncio.get_running_loop', return_value=mock_loop):
            # 连续 3 次失败，第 3 次触发告警但 create_task 抛异常
            for _ in range(3):
                # 不应抛异常
                await write_backup_record(
                    db=db, record_type='full', filename='erp_backup_test.zip',
                    status='success',
                )

        # 主流程未被中断，计数仍累加
        assert records_mod._record_write_fail_count == 3

    @pytest.mark.asyncio
    async def test_six_failures_trigger_two_alerts(self):
        """边界: 6次失败触发2次告警（每3次一次）"""
        from fastapi_app.services.backup import records as records_mod

        db = AsyncMock()
        db.flush = AsyncMock(side_effect=SQLAlchemyError('flush failed'))
        db.add = MagicMock()

        mock_alert = MagicMock()
        mock_alert.send_alert = AsyncMock()
        mock_loop = MagicMock()

        with patch('fastapi_app.services.backup.metrics.alert_service.alert_service',
                   mock_alert), \
             patch('asyncio.get_running_loop', return_value=mock_loop):
            for _ in range(6):
                await write_backup_record(
                    db=db, record_type='full', filename='erp_backup_test.zip',
                    status='success',
                )

        assert records_mod._record_write_fail_count == 6
        # 第3次和第6次各触发一次告警
        assert mock_loop.create_task.call_count == 2
        # 清理 coroutines
        for call in mock_loop.create_task.call_args_list:
            call[0][0].close()

    @pytest.mark.asyncio
    async def test_success_does_not_increment_fail_count(self):
        """边界: 写入成功时不累加失败计数、不告警"""
        from fastapi_app.services.backup import records as records_mod

        db = AsyncMock()
        db.flush = AsyncMock()  # 成功
        db.add = MagicMock()

        mock_alert = MagicMock()
        mock_alert.send_alert = AsyncMock()
        mock_loop = MagicMock()

        with patch('fastapi_app.services.backup.metrics.alert_service.alert_service',
                   mock_alert), \
             patch('asyncio.get_running_loop', return_value=mock_loop):
            await write_backup_record(
                db=db, record_type='full', filename='erp_backup_test.zip',
                status='success',
            )

        assert records_mod._record_write_fail_count == 0
        mock_loop.create_task.assert_not_called()
