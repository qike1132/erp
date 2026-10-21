"""图片上传端点契约测试（/api/v1/auth/upload）。

背景：产品图片新增「粘贴上传」后，剪贴板来源的 File 可能没有文件名/扩展名，
前端会按 MIME 补齐为 pasted-<ts>.<ext>。本套测试固化该契约：

- 文件名扩展名必须在白名单内，否则 400（前端补名是必要前提）；
- 文件内容签名必须与扩展名匹配；
- 大小上限 5MB。
"""
import base64
from unittest.mock import AsyncMock, patch

import pytest

# 1x1 PNG（含真实 PNG 文件头签名）
PNG_BYTES = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
)
JPEG_BYTES = b'\xff\xd8\xff\xe0' + b'\x00' * 16
FAKE_PNG_BYTES = b'not-an-image-at-all'

SAVE_RESULT = {'url': '/static/uploads/x.png', 'id': 1, 'storage_key': 'x.png'}


async def _upload(client, filename: str, content: bytes, content_type: str = 'image/png'):
    return await client.post(
        '/api/v1/auth/upload',
        files={'file': (filename, content, content_type)},
    )


@pytest.mark.asyncio
async def test_upload_pasted_filename_with_extension_ok(client):
    """前端补名后的粘贴文件名（pasted-<ts>.png）应上传成功"""
    with patch('fastapi_app.services.storage_service.save_upload', new=AsyncMock(return_value=SAVE_RESULT)):
        resp = await _upload(client, 'pasted-1789105172810.png', PNG_BYTES)

    assert resp.status_code == 200
    assert resp.json()['success'] is True
    assert resp.json()['url'] == SAVE_RESULT['url']


@pytest.mark.asyncio
async def test_upload_clipboard_default_filename_ok(client):
    """Chromium 剪贴板默认文件名 image.png 应上传成功"""
    with patch('fastapi_app.services.storage_service.save_upload', new=AsyncMock(return_value=SAVE_RESULT)):
        resp = await _upload(client, 'image.png', PNG_BYTES)

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_upload_without_extension_rejected(client):
    """无扩展名文件名会被拒 —— 前端必须补齐扩展名（补名逻辑的存在理由）"""
    resp = await _upload(client, 'pasted-1789105172810', PNG_BYTES)
    assert resp.status_code == 400
    assert '文件类型' in resp.json()['detail']


@pytest.mark.asyncio
async def test_upload_empty_filename_rejected(client):
    """空文件名会被拒（422）。

    httpx 对 filename='' 的分片不写 filename 参数，multipart 把它解析成普通字符串字段，
    请求模型 `Expected UploadFile, received str` 先拒 → 处理器的 `if not file.filename`
    对这条输入不可达（旧断言写成 400/422 两可，正是没查清是哪一层在拦）。
    """
    resp = await _upload(client, '', PNG_BYTES)
    assert resp.status_code == 422, f"空文件名应由请求模型拒绝 422，实测 {resp.status_code}: {resp.text}"
    assert 'Expected UploadFile' in resp.json()['detail'], f"应是 UploadFile 字段类型校验拦下，实测 {resp.text}"


@pytest.mark.asyncio
async def test_upload_unsupported_extension_rejected(client):
    """白名单外的扩展名（webp/bmp）拒绝"""
    for name in ('a.webp', 'a.bmp', 'a.exe'):
        resp = await _upload(client, name, PNG_BYTES)
        assert resp.status_code == 400, name


@pytest.mark.asyncio
async def test_upload_content_signature_mismatch_rejected(client):
    """内容不是图片（或与扩展名不符）时拒绝"""
    resp = await _upload(client, 'fake.png', FAKE_PNG_BYTES)
    assert resp.status_code == 400
    assert '扩展名' in resp.json()['detail']


@pytest.mark.asyncio
async def test_upload_jpeg_extension_matches_content(client):
    """jpeg 扩展名 + JPEG 签名应通过"""
    with patch('fastapi_app.services.storage_service.save_upload', new=AsyncMock(return_value=SAVE_RESULT)):
        resp = await _upload(client, 'pasted-1.jpg', JPEG_BYTES, 'image/jpeg')
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_upload_oversize_rejected(client):
    """超过 5MB 拒绝"""
    big = PNG_BYTES + b'\x00' * (5 * 1024 * 1024)
    resp = await _upload(client, 'big.png', big)
    assert resp.status_code == 400
    assert '大小' in resp.json()['detail']
