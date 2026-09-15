"""
备份服务单元测试

测试 backup_service.py 的核心函数。
"""
import json
import os
import zipfile
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from fastapi_app.services.backup import (
    BACKUP_FORMAT_VERSION,
    BACKUP_MAX_COUNT,
    BACKUP_RETENTION_DAYS,
    BackupError,
    BackupFileError,
    BackupLockError,
    RestoreError,
    build_column_type_map,
    cleanup_old_backups,
    delete_backup_file,
    deserialize_value,
    ensure_backup_dir,
    get_checksum_tables,
    list_backup_files,
    quote_table,
    serialize_value,
    sha256_bytes,
    sha256_file,
    validate_backup_file,
)

# ---------------------------------------------------------------------------
# 工具函数测试
# ---------------------------------------------------------------------------

class TestSha256:
    def test_sha256_bytes(self):
        result = sha256_bytes(b'hello world')
        assert len(result) == 64
        assert result == 'b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9'

    def test_sha256_bytes_empty(self):
        result = sha256_bytes(b'')
        assert len(result) == 64

    def test_sha256_file(self, tmp_path):
        test_file = tmp_path / 'test.txt'
        test_file.write_text('hello world')
        result = sha256_file(test_file)
        assert result == sha256_bytes(b'hello world')

    def test_sha256_file_not_exists(self, tmp_path):
        test_file = tmp_path / 'nonexistent.txt'
        result = sha256_file(test_file)
        assert result is None


class TestQuoteTable:
    def test_valid_table_name(self):
        assert quote_table('users') == '"users"'
        assert quote_table('order_items') == '"order_items"'
        assert quote_table('Table123') == '"Table123"'

    def test_invalid_table_name(self):
        with pytest.raises(ValueError, match='不安全的表名'):
            quote_table('users; DROP TABLE')

        with pytest.raises(ValueError, match='不安全的表名'):
            quote_table('users"--')


class TestSerializeValue:
    def test_none(self):
        assert serialize_value(None) is None

    def test_bool(self):
        assert serialize_value(True) is True
        assert serialize_value(False) is False

    def test_int(self):
        assert serialize_value(42) == 42

    def test_float(self):
        assert serialize_value(3.14) == 3.14

    def test_string(self):
        assert serialize_value('hello') == 'hello'

    def test_datetime(self):
        from datetime import datetime
        dt = datetime(2024, 1, 15, 10, 30, 0)
        assert serialize_value(dt) == '2024-01-15 10:30:00'

    def test_date(self):
        from datetime import date
        d = date(2024, 1, 15)
        assert serialize_value(d) == '2024-01-15'

    def test_decimal(self):
        from decimal import Decimal
        assert serialize_value(Decimal('3.14')) == 3.14

    def test_uuid(self):
        from uuid import UUID
        uid = UUID('12345678-1234-5678-1234-567812345678')
        assert serialize_value(uid) == '12345678-1234-5678-1234-567812345678'

    def test_bytes(self):
        result = serialize_value(b'\x00\x01\x02')
        assert result == '000102'


class TestDeserializeValue:
    def test_none(self):
        assert deserialize_value(None, MagicMock()) is None

    def test_datetime_string(self):
        from sqlalchemy import DateTime
        result = deserialize_value('2024-01-15 10:30:00', DateTime())
        assert result == datetime(2024, 1, 15, 10, 30, 0)

    def test_date_string(self):
        from sqlalchemy import Date
        result = deserialize_value('2024-01-15', Date())
        assert result == datetime(2024, 1, 15).date()

    def test_bool_from_int(self):
        from sqlalchemy import Boolean
        assert deserialize_value(1, Boolean()) is True
        assert deserialize_value(0, Boolean()) is False


class TestBuildColumnTypeMap:
    def test_basic(self):
        table = MagicMock()
        col1 = MagicMock()
        col1.name = 'id'
        col1.type = 'INTEGER'
        col2 = MagicMock()
        col2.name = 'name'
        col2.type = 'VARCHAR'
        table.columns = [col1, col2]
        result = build_column_type_map(table)
        assert result == {'id': 'INTEGER', 'name': 'VARCHAR'}


# ---------------------------------------------------------------------------
# 备份文件操作测试
# ---------------------------------------------------------------------------

class TestEnsureBackupDir:
    def test_creates_directory(self, tmp_path):
        with patch('fastapi_app.services.backup.records.BACKUP_DIR', tmp_path / 'backups'):
            ensure_backup_dir()
            assert (tmp_path / 'backups').exists()


class TestValidateBackupFile:
    def test_invalid_zip(self):
        with pytest.raises(BackupFileError, match='无效的 ZIP 文件'):
            validate_backup_file(b'not a zip file', 'test.zip')

    def test_zip_without_manifest(self, tmp_path):
        zip_path = tmp_path / 'test.zip'
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr('dummy.txt', 'hello')
        with pytest.raises(BackupFileError, match='缺少 manifest.json'):
            validate_backup_file(zip_path.read_bytes(), 'test.zip')

    def test_valid_zip(self, tmp_path):
        zip_path = tmp_path / 'test.zip'
        manifest = {
            'version': '2.0',
            'type': 'full',
            'exported_at': '2024-01-15 10:30:00',
            'exported_by': 'admin',
            'remark': 'test backup',
            'table_count': 5,
            'total_rows': 100,
            'includes': {},
            'checksums': {},
        }
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr('manifest.json', json.dumps(manifest))
            zf.writestr('database/dump.sql.gz', b'dummy')

        result = validate_backup_file(zip_path.read_bytes(), 'test.zip')
        assert result['format'] == 'zip'
        assert result['version'] == '2.0'
        assert result['table_count'] == 5
        assert result['total_rows'] == 100

    def test_valid_json(self):
        backup_data = {
            'version': '1.0',
            'exported_at': '2024-01-15 10:30:00',
            'exported_by': 'admin',
            'tables': {
                'users': {'columns': ['id', 'name'], 'rows': [{'id': 1, 'name': 'test'}], 'count': 1}
            }
        }
        result = validate_backup_file(
            json.dumps(backup_data).encode(),
            'test.json'
        )
        assert result['format'] == 'json'
        assert result['table_count'] == 1

    def test_json_without_tables(self):
        with pytest.raises(BackupFileError, match='缺少 tables 字段'):
            validate_backup_file(b'{"version": "1.0"}', 'test.json')


class TestDeleteBackupFile:
    def test_delete_success(self, tmp_path):
        test_file = tmp_path / 'erp_backup_20240115_103000.zip'
        test_file.write_bytes(b'dummy')
        with patch('fastapi_app.services.backup.records.BACKUP_DIR', tmp_path):
            result = delete_backup_file('erp_backup_20240115_103000.zip')
            assert result == 'erp_backup_20240115_103000.zip'
            assert not test_file.exists()

    def test_delete_not_found(self, tmp_path):
        with patch('fastapi_app.services.backup.records.BACKUP_DIR', tmp_path):
            with pytest.raises(BackupFileError, match='不存在'):
                delete_backup_file('nonexistent.zip')

    def test_delete_invalid_filename(self):
        with pytest.raises(BackupFileError, match='无效的文件名'):
            delete_backup_file('../etc/passwd')


class TestListBackupFiles:
    def test_empty_directory(self, tmp_path):
        with patch('fastapi_app.services.backup.records.BACKUP_DIR', tmp_path):
            result = list_backup_files()
            assert result == []

    def test_list_files(self, tmp_path):
        # 创建测试文件
        (tmp_path / 'erp_backup_20240115_103000.zip').write_bytes(b'dummy')
        (tmp_path / 'erp_incremental_20240115_120000.zip').write_bytes(b'dummy')
        (tmp_path / 'other_file.txt').write_bytes(b'dummy')  # 不应被列出

        with patch('fastapi_app.services.backup.records.BACKUP_DIR', tmp_path):
            result = list_backup_files()
            assert len(result) == 2
            filenames = [b['filename'] for b in result]
            assert 'erp_backup_20240115_103000.zip' in filenames
            assert 'erp_incremental_20240115_120000.zip' in filenames
            assert 'other_file.txt' not in filenames


# ---------------------------------------------------------------------------
# 备份保留策略测试
# ---------------------------------------------------------------------------

class TestCleanupOldBackups:
    def test_cleanup_empty_directory(self, tmp_path):
        with patch('fastapi_app.services.backup.records.BACKUP_DIR', tmp_path):
            result = cleanup_old_backups()
            assert result['deleted_count'] == 0
            assert result['kept_count'] == 0

    def test_cleanup_old_files(self, tmp_path):
        # 创建旧备份文件
        old_file = tmp_path / 'erp_backup_20240101_000000.zip'
        old_file.write_bytes(b'dummy')
        # 设置修改时间为 31 天前
        old_time = (datetime.now() - timedelta(days=31)).timestamp()
        os.utime(old_file, (old_time, old_time))

        # 创建新备份文件
        new_file = tmp_path / 'erp_backup_20240115_000000.zip'
        new_file.write_bytes(b'dummy')

        with patch('fastapi_app.services.backup.records.BACKUP_DIR', tmp_path):
            result = cleanup_old_backups()
            assert result['deleted_count'] == 1
            assert result['kept_count'] == 1
            assert not old_file.exists()
            assert new_file.exists()

    def test_cleanup_max_count(self, tmp_path):
        # 创建超过最大数量的备份
        for i in range(BACKUP_MAX_COUNT + 5):
            f = tmp_path / f'erp_backup_202401{i:02d}_000000.zip'
            f.write_bytes(b'dummy')

        with patch('fastapi_app.services.backup.records.BACKUP_DIR', tmp_path):
            result = cleanup_old_backups()
            assert result['deleted_count'] == 5
            assert result['kept_count'] == BACKUP_MAX_COUNT


# ---------------------------------------------------------------------------
# 时间戳归一化测试（修复增量备份级联误删 bug）
# ---------------------------------------------------------------------------

class TestNormalizeBackupTs:
    """normalize_backup_ts：统一文件名时间戳与 manifest base_timestamp 格式。

    文件名时间戳为 'YYYYMMDD_HHMMSS'，manifest base_timestamp 为
    'YYYY-MM-DD HH:MM:SS'。二者格式不一致时字符串比较恒为 False，曾导致
    所有增量备份被无条件误删（数据丢失）。此测试锁死该修复。

    函数位置：fastapi_app/services/backup/records.py 的**模块级纯函数**
    （2026-09-14 由 BackupCleanupService 的实例方法提升而来——它不依赖 self，
    放在类里导致测试必须实例化整个 Service 才能覆盖，且与 records 的
    文件名/时间戳约定分离）。
    """

    def test_filename_format_is_normalized(self):
        from fastapi_app.services.backup.records import normalize_backup_ts
        assert normalize_backup_ts('20260913_010000') == '2026-09-13 01:00:00'

    def test_manifest_format_is_unchanged(self):
        from fastapi_app.services.backup.records import normalize_backup_ts
        assert normalize_backup_ts('2026-09-13 01:00:00') == '2026-09-13 01:00:00'

    def test_empty_and_none(self):
        from fastapi_app.services.backup.records import normalize_backup_ts
        assert normalize_backup_ts('') == ''
        assert normalize_backup_ts(None) == ''

    def test_two_formats_compare_equal(self):
        """归一化后，文件名时间戳 <= manifest base_timestamp 应成立（修复前恒 False）"""
        from fastapi_app.services.backup.records import normalize_backup_ts
        filename_ts = normalize_backup_ts('20260913_010000')
        base_ts = normalize_backup_ts('2026-09-13 01:00:00')
        assert filename_ts == base_ts
        assert filename_ts <= base_ts

    def test_idempotent(self):
        """幂等性：归一化结果再归一化应不变（防重复调用产生二次破坏）"""
        from fastapi_app.services.backup.records import normalize_backup_ts
        once = normalize_backup_ts('20260913_010000')
        assert normalize_backup_ts(once) == once

    def test_non_timestamp_passthrough(self):
        """非法格式原样返回（去空格），不抛异常、不臆造格式"""
        from fastapi_app.services.backup.records import normalize_backup_ts
        assert normalize_backup_ts('not-a-ts') == 'not-a-ts'
        assert normalize_backup_ts('  2026-09-13 01:00:00  ') == '2026-09-13 01:00:00'

    def test_service_delegates_to_pure_function(self):
        """BackupCleanupService._normalize_backup_ts 必须委托到同一纯函数，
        防止将来有人只改一处造成实现漂移。"""
        from fastapi_app.services.backup.cleanup.service import BackupCleanupService
        from fastapi_app.services.backup.records import normalize_backup_ts

        # 不实例化（__init__ 依赖较重）：直接以 None 作 self 调用，验证委托
        for sample in ('20260913_010000', '2026-09-13 01:00:00', '', None, 'junk'):
            assert BackupCleanupService._normalize_backup_ts(None, sample) == normalize_backup_ts(sample)


# ---------------------------------------------------------------------------
# 级联删除端到端测试
#
# 为什么单独写这一组：TestNormalizeBackupTs 只验证纯函数**自身**正确，
# 无法发现"函数写对了但调用点忘了调用"的情况。2026-09-14 的重构中确实
# 出现过这种退化（records.py 提升了函数，却把两处调用点的 normalize 去掉了，
# 导致级联比较回退成原生字符串比较，所有增量备份被无条件删除 = 数据丢失），
# 而当时 7 个纯函数测试**全部通过**。因此必须从 cleanup_old_backups 入口
# 端到端锁死"比较发生在归一化之后"这一契约。
# ---------------------------------------------------------------------------

def _write_zip_with_manifest(path, base_timestamp):
    """生成一个含 manifest.json/base_timestamp 的增量备份 zip。"""
    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr('manifest.json', json.dumps({'base_timestamp': base_timestamp}))


class TestCascadeCleanup:
    def test_incremental_survives_when_base_full_exists(self, tmp_path):
        """基础全量还在 → 增量必须保留。

        回归点：文件名 'YYYYMMDD_HHMMSS' 与 manifest 'YYYY-MM-DD HH:MM:SS'
        混比较恒为 False（'20260913_010000' > '2026-09-13 01:00:00'，
        因第 6 位 '6' > '0'），会让 base_exists 恒 False → 增量被误删。
        """
        full = tmp_path / 'erp_backup_20260913_010000.zip'
        full.write_bytes(b'dummy')
        incr = tmp_path / 'erp_incremental_20260913_020000.zip'
        _write_zip_with_manifest(incr, '2026-09-13 01:00:00')  # 同一时刻的 manifest 格式

        with patch('fastapi_app.services.backup.records.BACKUP_DIR', tmp_path):
            result = cleanup_old_backups()

        assert incr.exists(), '基础全量仍在，增量备份不应被删除（归一化缺失会导致此处失败）'
        assert result['deleted_count'] == 0

    def test_incremental_cascade_deleted_when_base_full_removed(self, tmp_path):
        """基础全量已过期被删 → 依赖它的增量应级联删除（策略 3 正向生效）。

        与上一个测试配对：证明级联逻辑既不过度删除、也不失效。
        """
        old_ts = (datetime.now() - timedelta(days=BACKUP_RETENTION_DAYS + 5)).timestamp()
        full = tmp_path / 'erp_backup_20200101_010000.zip'
        full.write_bytes(b'dummy')
        os.utime(full, (old_ts, old_ts))  # 全量过期 → 必删

        incr = tmp_path / 'erp_incremental_20200101_020000.zip'
        _write_zip_with_manifest(incr, '2020-01-01 01:00:00')
        os.utime(incr, (old_ts, old_ts))

        with patch('fastapi_app.services.backup.records.BACKUP_DIR', tmp_path):
            result = cleanup_old_backups()

        assert not full.exists()
        assert not incr.exists(), '基础全量被删后，增量应级联删除'
        assert result['deleted_count'] == 2

    def test_incremental_survives_when_newer_base_exists(self, tmp_path):
        """存在更早（<=base_ts）的全量 → 增量保留，验证比较方向正确。"""
        full = tmp_path / 'erp_backup_20260901_000000.zip'  # 早于 base_ts
        full.write_bytes(b'dummy')
        incr = tmp_path / 'erp_incremental_20260913_020000.zip'
        _write_zip_with_manifest(incr, '2026-09-13 01:00:00')

        with patch('fastapi_app.services.backup.records.BACKUP_DIR', tmp_path):
            cleanup_old_backups()

        assert incr.exists()
        assert full.exists()


# ---------------------------------------------------------------------------
# 异常类测试
# ---------------------------------------------------------------------------

class TestExceptions:
    def test_backup_error(self):
        err = BackupError('test error')
        assert str(err) == 'test error'
        assert isinstance(err, Exception)

    def test_backup_lock_error(self):
        err = BackupLockError('lock failed')
        assert isinstance(err, BackupError)

    def test_backup_file_error(self):
        err = BackupFileError('file not found')
        assert isinstance(err, BackupError)

    def test_restore_error(self):
        err = RestoreError('restore failed')
        assert isinstance(err, BackupError)


# ---------------------------------------------------------------------------
# 常量测试
# ---------------------------------------------------------------------------

class TestConstants:
    def test_backup_format_version(self):
        assert BACKUP_FORMAT_VERSION == '2.0'

    def test_retention_config(self):
        assert BACKUP_RETENTION_DAYS == 30
        assert BACKUP_MAX_COUNT == 50


# ---------------------------------------------------------------------------
# get_checksum_tables 测试
# ---------------------------------------------------------------------------

class TestGetChecksumTables:
    def test_excludes_alembic_version(self):
        with patch('fastapi_app.shared_models.Base') as mock_base:
            table1 = MagicMock()
            table1.name = 'users'
            table2 = MagicMock()
            table2.name = 'alembic_version'
            table3 = MagicMock()
            table3.name = 'orders'
            mock_base.metadata.sorted_tables = [table1, table2, table3]

            result = get_checksum_tables()
            assert 'users' in result
            assert 'orders' in result
            assert 'alembic_version' not in result
