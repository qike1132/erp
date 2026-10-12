"""
备份服务单元测试

测试 backup_service.py 的核心函数。
"""
import json
import os
import zipfile
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from fastapi_app.services.backup import (
    BACKUP_FORMAT_VERSION,
    BackupError,
    BackupFileError,
    BackupLockError,
    RestoreError,
    build_column_type_map,
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
from fastapi_app.services.backup._constants import (
    RETENTION_COUNT_DEFAULT,
    RETENTION_COUNT_ENV,
    RETENTION_DAYS_DEFAULT,
    RETENTION_DAYS_ENV,
    retention_count,
    retention_days,
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
        (tmp_path / 'erp_auto_20240115_120000.zip').write_bytes(b'dummy')
        (tmp_path / 'other_file.txt').write_bytes(b'dummy')  # 不应被列出

        with patch('fastapi_app.services.backup.records.BACKUP_DIR', tmp_path):
            result = list_backup_files()
            assert len(result) == 2
            filenames = [b['filename'] for b in result]
            assert 'erp_backup_20240115_103000.zip' in filenames
            assert 'erp_auto_20240115_120000.zip' in filenames
            assert 'other_file.txt' not in filenames


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

    def test_retention_config(self, monkeypatch):
        """保留策略由 env 单一真源驱动（此前在本模块硬编码 30 天/50 份）。

        旧实现：_constants 硬编码 30/50，而 policy_service / cleanup 服务各自读 env
        （默认 30/100）⇒ 同一台机器上「策略显示保留 100 份」而「实际按 50 份删」。
        """
        monkeypatch.setenv(RETENTION_DAYS_ENV, '17')
        monkeypatch.setenv(RETENTION_COUNT_ENV, '9')
        assert retention_days() == 17
        assert retention_count() == 9

        monkeypatch.delenv(RETENTION_DAYS_ENV, raising=False)
        monkeypatch.delenv(RETENTION_COUNT_ENV, raising=False)
        assert retention_days() == RETENTION_DAYS_DEFAULT == 7
        assert retention_count() == RETENTION_COUNT_DEFAULT == 100

    def test_retention_constants_stay_importable(self, monkeypatch):
        """模块级常量是启动快照，必须与保留策略单源函数**等值**（P0-2 F-04）。

        修复前这里被放宽成 isinstance(int) + > 0：若有人把模块常量重新硬编码回
        旧值（份额 50），本测试不再报警。现在固定 env 后 reload 模块，逐个**等值**
        比对快照、单源函数与缺省口径（天数 7（全量-only 后改默认）/ 100 份）。
        """
        import importlib

        from fastapi_app.services.backup import _constants

        original = {key: os.environ.get(key) for key in (RETENTION_DAYS_ENV, RETENTION_COUNT_ENV)}
        try:
            # env 覆盖：reload 后的快照 == env 值 == 单源函数返回值
            monkeypatch.setenv(RETENTION_DAYS_ENV, '11')
            monkeypatch.setenv(RETENTION_COUNT_ENV, '7')
            overridden = importlib.reload(_constants)
            assert overridden.BACKUP_RETENTION_DAYS == overridden.retention_days() == 11
            assert overridden.BACKUP_MAX_COUNT == overridden.retention_count() == 7

            # env 缺省：reload 后的快照 == 缺省值 == 单源函数返回值
            monkeypatch.delenv(RETENTION_DAYS_ENV, raising=False)
            monkeypatch.delenv(RETENTION_COUNT_ENV, raising=False)
            defaulted = importlib.reload(_constants)
            assert RETENTION_DAYS_DEFAULT == 7
            assert RETENTION_COUNT_DEFAULT == 100
            assert defaulted.BACKUP_RETENTION_DAYS == defaulted.retention_days() == RETENTION_DAYS_DEFAULT
            assert defaulted.BACKUP_MAX_COUNT == defaulted.retention_count() == RETENTION_COUNT_DEFAULT
        finally:
            # 把模块快照还原到测试前的 env 口径，避免 reload 泄漏给同进程后续用例
            for key, value in original.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            importlib.reload(_constants)


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
