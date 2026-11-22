"""产品图片上传的产品管理权限回归测试。"""
from unittest.mock import AsyncMock, patch

import pytest

from fastapi_app.core.deps import _get_user_with_permissions
from fastapi_app.main import app
from fastapi_app.shared_models import Permission, User

_PNG_BYTES = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32
_SAVE_RESULT = {'url': '/static/uploads/product.png', 'id': 1, 'storage_key': 'product.png'}
_SAVE_UPLOAD = 'fastapi_app.services.storage_service.save_upload'


def _use_user_with(codes: list[str]) -> None:
    async def override():
        user = User(username='upload-user', password='x', is_super=False, status=True)
        user.permissions = [Permission(name=code, code=code) for code in codes]
        return user

    app.dependency_overrides[_get_user_with_permissions] = override


async def _upload(client):
    return await client.post(
        '/api/v1/auth/upload',
        files={'file': ('product.png', _PNG_BYTES, 'image/png')},
    )


@pytest.mark.asyncio
async def test_upload_image_without_product_manage_is_denied_before_save(client):
    _use_user_with([])
    save = AsyncMock(return_value=_SAVE_RESULT)

    with patch(_SAVE_UPLOAD, new=save):
        resp = await _upload(client)

    assert resp.status_code == 403
    save.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_image_with_product_manage_is_allowed(client):
    _use_user_with(['product_manage'])
    save = AsyncMock(return_value=_SAVE_RESULT)

    with patch(_SAVE_UPLOAD, new=save):
        resp = await _upload(client)

    assert resp.status_code == 200, resp.text
    assert resp.json()['success'] is True
    save.assert_awaited_once()
