"""WebSocket 权限主体必须由 ORM 会话返回实体，而不是裸主键。"""
import pytest

from fastapi_app.api.ws import _load_ws_user_from_session
from fastapi_app.shared_models import User


@pytest.mark.asyncio
async def test_load_ws_principal_returns_orm_user(async_db_session, admin_user):
    user, query_ok = await _load_ws_user_from_session(async_db_session, admin_user.id)

    assert query_ok is True
    assert isinstance(user, User)
    assert user.id == admin_user.id
    assert user.username == admin_user.username
    assert isinstance(user.permissions, list)


@pytest.mark.asyncio
async def test_load_ws_principal_rejects_disabled_user(async_db_session, normal_user):
    normal_user.status = False
    await async_db_session.flush()
    try:
        user, query_ok = await _load_ws_user_from_session(async_db_session, normal_user.id)
    finally:
        normal_user.status = True
        await async_db_session.flush()

    assert query_ok is True
    assert user is None
