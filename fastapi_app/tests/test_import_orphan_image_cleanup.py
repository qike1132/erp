"""Z04-R2：导入行 savepoint 回滚后，已落盘图片必须按 key 补偿删除。"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.services import batch_import_core


class _Nested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_failed_row_deletes_saved_image_keys(monkeypatch):
    deleted: list[list[str]] = []

    async def fake_delete(keys):
        deleted.append(list(keys))

    monkeypatch.setattr(
        'fastapi_app.services.storage_service.delete_storage_keys', fake_delete,
    )

    db = MagicMock()
    db.info = {}
    db.begin_nested = MagicMock(return_value=_Nested())
    db.flush = AsyncMock()

    async def handler(db, row, idx, context, debug):
        db.info['import_image_keys'].append('uploads/orphan.jpg')
        raise ValueError('行失败')

    count, messages = await batch_import_core._import_data_generic(
        db, [{'x': 1}], handler, use_savepoint=True,
    )

    assert count == 0
    assert messages and '行失败' in messages[0]
    assert deleted == [['uploads/orphan.jpg']]
    assert 'import_image_keys' not in db.info
