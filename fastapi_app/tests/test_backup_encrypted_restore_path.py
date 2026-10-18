"""加密备份的预览与还原通路：不允许出现「界面上根本走不通」的加密包。

背景（/backup 审计，high）
-------------------------
加密备份此前在 UI 上是**死路**，两处叠加：

1. `POST /backup/restore/plan` 对 `.enc` 一律抛普通 ValueError → 端点回
   `success=False, encrypted=False`；而前端的密码输入框和「确认还原」按钮分别以
   `plan.encrypted` / `plan.success` 为条件 ⇒ 输入框不出现、按钮永远禁用。
2. `POST /backup/restore-by-name/{f}` 与 `/async-restore-by-name/{f}` 声明
   `password: str | None = Body(None)`（未 embed），FastAPI 因此要求 body 是**裸字符串**；
   前端发的是 `{"password": "..."}` ⇒ 422。

本文件把两条通路钉死：预览侧能带密码读到 manifest，还原侧 body 收的是对象。
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from fastapi_app.main import app
from fastapi_app.services.backup import restore_plan as rp

_PW = 'correct-horse-battery'
_MANIFEST = {
    'encrypted': True,
    'exported_at': '2026-09-28 10:00:00',
    'tables': {'orders': {'rows': 3}, 'order_items': {'rows': 7}},
}


def _zip_with_manifest(manifest: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('manifest.json', json.dumps(manifest))
        zf.writestr('data/orders.json', '[]')
    return buf.getvalue()


def _encrypted_backup(tmp_path, password: str = _PW):
    from fastapi_app.core.backup_encryption import encrypt_backup_auto

    raw = _zip_with_manifest(_MANIFEST)
    ciphertext, _meta = encrypt_backup_auto(raw, password)
    enc = tmp_path / 'erp_backup_20260928.zip.enc'
    enc.write_bytes(ciphertext)
    return enc


# ---------------------------------------------------------------------------
# 预览侧：加密包不再是「无路可走」
# ---------------------------------------------------------------------------

def test_encrypted_without_password_raises_dedicated_error(tmp_path) -> None:
    """必须抛 EncryptedBackupError —— 端点是靠这个类型把 encrypted=True 回给前端的。"""
    _encrypted_backup(tmp_path)

    with pytest.raises(rp.EncryptedBackupError):
        rp.read_manifest_from_backup('erp_backup_20260928.zip.enc', base_dir=tmp_path)


def test_encrypted_error_is_a_value_error_for_backcompat() -> None:
    """仍应是 ValueError 子类：既有 `except ValueError` 调用方不会漏接。"""
    assert issubclass(rp.EncryptedBackupError, ValueError)


def test_encrypted_preview_with_password_returns_manifest(tmp_path) -> None:
    _encrypted_backup(tmp_path)

    manifest = rp.read_manifest_from_backup(
        'erp_backup_20260928.zip.enc', base_dir=tmp_path, password=_PW,
    )

    assert manifest['tables'] == _MANIFEST['tables']
    assert manifest['encrypted'] is True, '解密后 manifest 必须自报加密，前端据此保留密码框'


def test_wrong_password_is_plain_value_error_not_encrypted_error(tmp_path) -> None:
    """密码错与「缺密码」要能区分：前者是真失败，后者只是还差一步输入。"""
    _encrypted_backup(tmp_path)

    with pytest.raises(ValueError) as ei:
        rp.read_manifest_from_backup(
            'erp_backup_20260928.zip.enc', base_dir=tmp_path, password='wrong-password',  # secret-scan:allow 测试夹具：故意错误的口令
        )

    assert not isinstance(ei.value, rp.EncryptedBackupError)


def test_plain_zip_needs_no_password(tmp_path) -> None:
    """未加密备份的既有行为不能被这次改动波及。"""
    (tmp_path / 'plain.zip').write_bytes(_zip_with_manifest({'tables': {'orders': {'rows': 1}}}))

    manifest = rp.read_manifest_from_backup('plain.zip', base_dir=tmp_path)

    assert manifest['tables'] == {'orders': {'rows': 1}}


def test_missing_file_still_file_not_found(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        rp.read_manifest_from_backup('nope.zip.enc', base_dir=tmp_path)


# ---------------------------------------------------------------------------
# 还原侧：body 是对象（{"password": ...}），不是裸字符串
# ---------------------------------------------------------------------------

def _request_body_schema(path_suffix: str) -> tuple[dict, list[str]]:
    """取某端点 POST 请求体的 (schema, required)。"""
    paths = app.openapi()['paths']
    match = [p for p in paths if p.endswith(path_suffix)]
    assert match, f'OpenAPI 里找不到端点 {path_suffix}'
    op = paths[match[0]]['post']
    schema = op['requestBody']['content']['application/json']['schema']
    ref = schema.get('$ref')
    if ref:
        schema = app.openapi()['components']['schemas'][ref.rsplit('/', 1)[-1]]
    return schema, schema.get('required', [])


@pytest.mark.parametrize(
    'suffix',
    ['/restore-by-name/{filename}', '/async-restore-by-name/{filename}'],
)
def test_restore_by_name_body_is_an_object_with_optional_password(suffix: str) -> None:
    """`embed=True` 的回归锁。

    未 embed 时 FastAPI 要求 body 是裸字符串 `"pw"`，而前端发的是
    `{"password": "pw"}` → 422，加密还原在界面上必然失败。
    """
    schema, required = _request_body_schema(suffix)

    assert 'password' in schema.get('properties', {}), (
        f'{suffix} 的请求体里没有 password 字段 —— body 不是对象（多半漏了 embed=True）'
    )
    assert 'password' not in required, 'password 必须是可选字段'


def test_plan_endpoint_accepts_password_field() -> None:
    """预览也要带密码，否则加密包永远只能显示「预览失败」。"""
    paths = app.openapi()['paths']
    match = [p for p in paths if p.endswith('/restore/plan')]
    assert match, 'OpenAPI 里找不到 /restore/plan'
    ref = paths[match[0]]['post']['requestBody']['content']['application/json']['schema']['$ref']
    schema = app.openapi()['components']['schemas'][ref.rsplit('/', 1)[-1]]

    assert 'password' in schema['properties']
    assert 'password' not in schema.get('required', [])


# ---------------------------------------------------------------------------
# 2026-10-18 OCR 评审：AUD-07 只改了一半 —— .json.enc 的解密此前只加了上传路径
# ---------------------------------------------------------------------------

def test_server_restore_endpoints_decrypt_json_enc() -> None:
    """两个「从服务器恢复」端点必须走同一套格式识别（含 .enc 解密）。

    旧实现只在上传路径 `_read_backup_file` 里解密，`/restore-by-name` 与
    `/async-restore-by-name` 仍是裸 `json.loads(content)` —— 加密 JSON 备份从
    服务器还原时必定 400「格式无效」，而错误信息完全不提加密。
    """
    source = Path(
        'fastapi_app/api/v1/endpoints/backup/restore.py',
    ).read_text(encoding='utf-8')

    # 两条服务器恢复路径都要经过共享识别函数
    assert source.count('await _sniff_server_backup_format(') >= 2, (
        '「从服务器恢复」的端点没有都走 _sniff_server_backup_format —— '
        '加密 JSON 备份会以「格式无效」失败（AUD-07 漏改）'
    )


@pytest.mark.asyncio
async def test_sniff_server_backup_format_decrypts_json_enc(tmp_path) -> None:
    """`.json.enc` 解密后应被识别为 JSON（is_zip=False）并返回明文。"""
    from fastapi_app.api.v1.endpoints.backup.restore import _sniff_server_backup_format
    from fastapi_app.core.backup_encryption import encrypt_backup_auto

    plaintext = json.dumps({'tables': {'orders': []}}).encode()
    ciphertext, _meta = encrypt_backup_auto(plaintext, _PW)

    content, is_zip = await _sniff_server_backup_format(
        ciphertext, 'erp_backup_20260928.json.enc', _PW,
    )

    assert is_zip is False
    assert json.loads(content) == {'tables': {'orders': []}}


@pytest.mark.asyncio
async def test_sniff_server_backup_format_requires_password_for_enc(tmp_path) -> None:
    """加密文件但没给密码 → 明确的 400，而不是「无法识别的备份文件格式」。"""
    from fastapi import HTTPException

    from fastapi_app.api.v1.endpoints.backup.restore import _sniff_server_backup_format
    from fastapi_app.core.backup_encryption import encrypt_backup_auto

    plaintext = json.dumps({'tables': {'orders': []}}).encode()
    ciphertext, _meta = encrypt_backup_auto(plaintext, _PW)

    with pytest.raises(HTTPException) as ei:
        await _sniff_server_backup_format(ciphertext, 'erp_backup_20260928.json.enc', None)
    assert ei.value.status_code == 400
    assert '加密' in str(ei.value.detail)


@pytest.mark.asyncio
async def test_sniff_server_backup_format_plain_json_unchanged() -> None:
    """明文 JSON / ZIP 不加密也能识别（不因本次改动回归）。"""
    from fastapi_app.api.v1.endpoints.backup.restore import _sniff_server_backup_format

    raw = json.dumps({'tables': {'orders': []}}).encode()
    content, is_zip = await _sniff_server_backup_format(raw, 'erp_backup.json', None)
    assert is_zip is False and json.loads(content) == {'tables': {'orders': []}}

    zip_bytes = _zip_with_manifest(_MANIFEST)
    content, is_zip = await _sniff_server_backup_format(zip_bytes, 'erp_backup.zip', None)
    assert is_zip is True and content == zip_bytes
