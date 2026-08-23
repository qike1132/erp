"""
M5 收尾测试(TECHNICAL_PLAN.md v2 §7 M5)

覆盖:
1. _audit_export_download:审计条目字段(action=EXPORT/resource_type=backup/detail)
   与审计失败不阻断下载
2. GET /export 下载:明文/加密分支均触发显式审计
3. GET /export-enhanced:同样触发审计
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ===========================================================================
# 1. _audit_export_download 单元测试
# ===========================================================================

def _make_request(ip: str = '192.168.1.10', ua: str = 'pytest-agent'):
    request = MagicMock()
    request.client.host = ip
    request.headers = {'user-agent': ua}
    request.state.request_id = 'req-123'
    return request


class TestAuditExportDownload:
    @pytest.mark.asyncio
    async def test_entry_fields(self):
        from fastapi_app.api.v1.endpoints.backup.export import _audit_export_download

        request = _make_request()
        user = MagicMock()
        user.id = 7
        user.username = 'admin'

        buffer_mock = AsyncMock()
        with patch(
            'fastapi_app.api.v1.endpoints.backup.export._buffer_audit_entry',
            new=buffer_mock,
        ):
            await _audit_export_download(
                request, user,
                filename='erp_backup_20260823_100000.zip.enc',
                format='zip', encrypted=True, size=1024, remark='演练',
            )

        buffer_mock.assert_awaited_once()
        entry = buffer_mock.await_args.args[0]
        assert entry['action'] == 'EXPORT'
        assert entry['resource_type'] == 'backup'
        assert entry['user_id'] == 7
        assert entry['username'] == 'admin'
        assert entry['ip_address'] == '192.168.1.10'
        assert entry['user_agent'] == 'pytest-agent'
        assert entry['request_id'] == 'req-123'
        assert entry['status_code'] == 200
        detail = json.loads(entry['detail'])
        assert detail['filename'] == 'erp_backup_20260823_100000.zip.enc'
        assert detail['encrypted'] is True
        assert detail['size'] == 1024
        assert detail['remark'] == '演练'

    @pytest.mark.asyncio
    async def test_x_forwarded_for_preferred(self):
        from fastapi_app.api.v1.endpoints.backup.export import _audit_export_download

        request = _make_request()
        request.headers = {'user-agent': 'ua', 'x-forwarded-for': '10.0.0.9, 10.0.0.1'}
        user = MagicMock()

        buffer_mock = AsyncMock()
        with patch(
            'fastapi_app.api.v1.endpoints.backup.export._buffer_audit_entry',
            new=buffer_mock,
        ):
            await _audit_export_download(
                request, user, filename='x.zip', format='zip',
                encrypted=False, size=10, remark='',
            )
        entry = buffer_mock.await_args.args[0]
        assert entry['ip_address'] == '10.0.0.9'

    @pytest.mark.asyncio
    async def test_audit_failure_does_not_raise(self):
        """审计写入失败只告警，不能让下载 500。"""
        from fastapi_app.api.v1.endpoints.backup.export import _audit_export_download

        request = _make_request()
        user = MagicMock()

        with patch(
            'fastapi_app.api.v1.endpoints.backup.export._buffer_audit_entry',
            new=AsyncMock(side_effect=RuntimeError('redis down')),
        ):
            await _audit_export_download(
                request, user, filename='x.zip', format='zip',
                encrypted=False, size=10, remark='',
            )


# ===========================================================================
# 2. GET /export 端点级:下载触发显式审计
# ===========================================================================

class TestExportEndpointAudit:
    @pytest.mark.asyncio
    async def test_export_zip_plaintext_triggers_audit(self, client, tmp_path):
        fake_zip = tmp_path / 'erp_backup_fake.zip'
        fake_zip.write_bytes(b'PK\x03\x04' + b'0' * 100)
        expected_size = fake_zip.stat().st_size
        manifest = {'zip_size': expected_size, 'table_count': 2, 'total_rows': 5}

        audit_mock = AsyncMock()
        with patch(
            'fastapi_app.api.v1.endpoints.backup.export.backup_service.create_full_backup_to_file',
            new=AsyncMock(return_value=(fake_zip, manifest)),
        ), patch(
            'fastapi_app.api.v1.endpoints.backup.export._audit_export_download',
            new=audit_mock,
        ):
            resp = await client.get(
                '/api/v1/backup/export',
                params={'encrypt': False, 'format': 'zip', 'remark': 'M5测试'},
            )

        assert resp.status_code == 200
        audit_mock.assert_awaited_once()
        kwargs = audit_mock.await_args.kwargs
        assert kwargs['filename'].endswith('.zip')
        assert kwargs['encrypted'] is False
        assert kwargs['format'] == 'zip'
        assert kwargs['remark'] == 'M5测试'
        assert kwargs['size'] == expected_size

    @pytest.mark.asyncio
    async def test_export_zip_encrypted_triggers_audit(self, client, tmp_path):
        fake_zip = tmp_path / 'erp_backup_fake2.zip'
        fake_zip.write_bytes(b'PK\x03\x04' + b'0' * 100)
        manifest = {'zip_size': fake_zip.stat().st_size}

        audit_mock = AsyncMock()
        with patch(
            'fastapi_app.api.v1.endpoints.backup.export.backup_service.create_full_backup_to_file',
            new=AsyncMock(return_value=(fake_zip, manifest)),
        ), patch(
            'fastapi_app.api.v1.endpoints.backup.export._audit_export_download',
            new=audit_mock,
        ):
            resp = await client.get(
                '/api/v1/backup/export',
                params={'encrypt': True, 'format': 'zip', 'password': 'secret-pw'},
            )

        assert resp.status_code == 200
        audit_mock.assert_awaited_once()
        kwargs = audit_mock.await_args.kwargs
        assert kwargs['filename'].endswith('.zip.enc')
        assert kwargs['encrypted'] is True

    @pytest.mark.asyncio
    async def test_export_json_triggers_audit(self, client, tmp_path):
        audit_mock = AsyncMock()
        with patch(
            'fastapi_app.api.v1.endpoints.backup.export.backup_service.execute_legacy_backup_to_bytes',
            new=AsyncMock(return_value=b'{"tables": {}}'),
        ), patch(
            'fastapi_app.api.v1.endpoints.backup.export._audit_export_download',
            new=audit_mock,
        ):
            resp = await client.get(
                '/api/v1/backup/export',
                params={'encrypt': False, 'format': 'json'},
            )

        assert resp.status_code == 200
        audit_mock.assert_awaited_once()
        kwargs = audit_mock.await_args.kwargs
        assert kwargs['filename'].endswith('.json')
        assert kwargs['format'] == 'json'
        assert kwargs['size'] == len(b'{"tables": {}}')

    @pytest.mark.asyncio
    async def test_export_enhanced_triggers_audit(self, client, tmp_path):
        fake_zip = tmp_path / 'erp_backup_fake3.zip'
        fake_zip.write_bytes(b'PK\x03\x04' + b'0' * 100)

        audit_mock = AsyncMock()
        with patch(
            'fastapi_app.api.v1.endpoints.backup.export.backup_service.create_full_backup_to_file',
            new=AsyncMock(return_value=(fake_zip, {})),
        ), patch(
            'fastapi_app.api.v1.endpoints.backup.export._audit_export_download',
            new=audit_mock,
        ):
            resp = await client.get(
                '/api/v1/backup/export-enhanced',
                params={'encrypt': False, 'format': 'zip'},
            )

        assert resp.status_code == 200
        audit_mock.assert_awaited_once()
        assert audit_mock.await_args.kwargs['filename'].endswith('.zip')


# ===========================================================================
# 4. JSON 列序列化往返（REV-JSON 演练发现修复）
# ===========================================================================

class TestJsonColumnRoundTrip:
    """M5 演练发现:备份时 JSON 列被 str() 成 Python 字面量(单引号),
    恢复时 asyncpg 无法解析导致数据类型 json 输入语法无效。"""

    def test_serialize_dict_as_valid_json(self):
        from fastapi_app.services.backup.json_backup import serialize_value

        val = {'new': 'cancelled', 'old': 'in_progress', 'field': 'status'}
        out = serialize_value(val)
        # 必须是合法 JSON 字符串(双引号),而非 Python repr(单引号)
        assert out == '{"new": "cancelled", "old": "in_progress", "field": "status"}'
        # json.loads 可解析
        assert json.loads(out) == val

    def test_serialize_list_as_valid_json(self):
        from fastapi_app.services.backup.json_backup import serialize_value

        val = [{'fabric_name': '氨纶', 'unit_price': None}]
        out = serialize_value(val)
        assert json.loads(out) == val
        assert "'" not in out  # 不允许单引号 Python 字面量

    def test_deserialize_json_string_returns_struct(self):
        from fastapi_app.services.backup.json_backup import deserialize_value
        from sqlalchemy.dialects.postgresql import JSONB

        s = '{"new": "cancelled", "old": "in_progress"}'
        out = deserialize_value(s, JSONB())
        assert isinstance(out, dict)
        assert out['new'] == 'cancelled'

    def test_deserialize_json_non_string_passthrough(self):
        from fastapi_app.services.backup.json_backup import deserialize_value
        from sqlalchemy.dialects.postgresql import JSONB

        # 已是结构体则原样返回
        out = deserialize_value({'a': 1}, JSONB())
        assert out == {'a': 1}

    def test_deserialize_invalid_json_string_returns_str(self):
        from fastapi_app.services.backup.json_backup import deserialize_value
        from sqlalchemy.dialects.postgresql import JSONB

        # 旧备份的 Python 字面量无法解析,降级原样返回(保持向后兼容)
        legacy = "{'new': 'cancelled', 'old': 'in_progress'}"
        out = deserialize_value(legacy, JSONB())
        assert out == legacy
