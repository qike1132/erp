"""备份三连审计修复回归（2026-10-17 AUD-06/07/08）

- AUD-06：恢复编排器默认解密器必须能解开 meta 前缀格式（旧 /save 产出）。
- AUD-07：`.json.enc` 上传必须能被识别并解密（此前三探针全不匹配 → 400）。
- AUD-08：备份设置响应必须显式告知实际生效来源是环境变量。
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.api.v1.endpoints.backup._deps import _encrypt_backup_data
from fastapi_app.api.v1.endpoints.backup.restore import _read_backup_file
from fastapi_app.services.backup.adapters import DefaultArchiveDecryptorAdapter
from fastapi_app.services.backup.settings_service import get_settings

PASSWORD = 'audit-test-password'  # secret-scan:allow 测试夹具口令，非真实凭据


class _FakeUpload:
    def __init__(self, filename: str, data: bytes):
        self.filename = filename
        self._data = data
        # B2-08（2026-10-24 审计）：_read_backup_file 按声明值预检，须带 size
        self.size = len(data)

    async def read(self) -> bytes:
        return self._data


@pytest.mark.asyncio
async def test_decryptor_handles_meta_prefixed_format():
    """AUD-06：meta 前缀（格式 B）密文必须能解开——此前误报「密码错误」"""
    plaintext = b'{"hello": "world"}'
    encrypted = _encrypt_backup_data(plaintext, PASSWORD)

    adapter = DefaultArchiveDecryptorAdapter()
    result = await adapter.decrypt_if_needed(encrypted, PASSWORD, True)

    assert result == plaintext


@pytest.mark.asyncio
async def test_json_enc_upload_is_recognized():
    """AUD-07：.json.enc 上传必须解密后按 JSON 识别，而不是 400"""
    plaintext = b'{"success": true}'
    encrypted = _encrypt_backup_data(plaintext, PASSWORD)

    content, is_zip, filename = await _read_backup_file(
        _FakeUpload('erp_backup_20261017.json.enc', encrypted), PASSWORD,
    )

    assert content == plaintext
    assert is_zip is False
    assert filename.endswith('.json.enc')


@pytest.mark.asyncio
async def test_json_enc_upload_without_password_has_clear_error():
    """缺密码时必须给出「需要 X-Backup-Password」而不是「无法识别格式」"""
    from fastapi import HTTPException

    encrypted = _encrypt_backup_data(b'{"success": true}', PASSWORD)
    with pytest.raises(HTTPException) as exc:
        await _read_backup_file(_FakeUpload('x.json.enc', encrypted), None)

    assert exc.value.status_code == 400
    assert 'X-Backup-Password' in str(exc.value.detail)


@pytest.mark.asyncio
async def test_settings_response_declares_env_source():
    """AUD-08：表值仅记录不生效，响应必须显式返回 effective_source=env"""
    row = MagicMock()
    row.backup_dir = 'D:\\saved-but-unused'
    row.retention_days = 3
    row.max_count = 5
    row.encryption_mode = 'off'
    row.updated_by = 'admin'
    row.updated_at = None
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = row
    db.execute.return_value = result_mock

    result = await get_settings(db)

    assert result['effective_source'] == 'env'
    assert result['effective_backup_dir']
    assert result['backup_dir'] == 'D:\\saved-but-unused'  # 表值仍原样返回（仅记录）
