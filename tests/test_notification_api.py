"""通知 API：用户隔离、未读筛选、分页边界和全部已读范围。"""
from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio

from fastapi_app.core.deps import get_current_user_id
from fastapi_app.main import app
from fastapi_app.shared_models import Notification, User

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]
PREFIX = "/api/v1/notifications"


@pytest_asyncio.fixture
async def notification_fixture(async_db_session):
    """使用独立用户，避免共享 normal_user 上的历史通知污染精确计数。"""
    tag = uuid4().hex[:8]
    normal = User(
        username=f"notify-user-{tag}", password="x", is_super=False, status=True,
    )
    other = User(
        username=f"notify-other-{tag}", password="x", is_super=False, status=True,
    )
    async_db_session.add_all([normal, other])
    await async_db_session.flush()
    rows = [
        Notification(user_id=normal.id, type="test", title=f"未读A-{tag}", is_read=False),
        Notification(user_id=normal.id, type="test", title=f"未读B-{tag}", is_read=False),
        Notification(user_id=normal.id, type="test", title=f"已读-{tag}", is_read=True),
        Notification(user_id=other.id, type="test", title=f"管理员未读-{tag}", is_read=False),
    ]
    async_db_session.add_all(rows)
    await async_db_session.flush()
    return {"tag": tag, "normal": normal, "admin": other, "rows": rows}


@pytest.fixture
def as_user():
    """临时切换通知端点读取的当前用户；严格鉴权仍由真实管理员 token 通过。"""
    def _activate(user_id: int):
        app.dependency_overrides[get_current_user_id] = lambda: user_id
    yield _activate
    app.dependency_overrides.pop(get_current_user_id, None)


async def test_unread_list_and_pagination_are_scoped_to_current_user(
    async_client, auth_headers, notification_fixture, as_user
):
    fixture = notification_fixture
    as_user(fixture["normal"].id)

    unread = await async_client.get(f"{PREFIX}/unread-count", headers=auth_headers)
    assert unread.status_code == 200
    assert unread.json()["count"] == 2

    only_unread = await async_client.get(
        PREFIX, params={"only_unread": True, "page_size": 100}, headers=auth_headers,
    )
    body = only_unread.json()
    assert body["total"] == 2
    assert {row["title"] for row in body["data"]} == {
        f"未读A-{fixture['tag']}", f"未读B-{fixture['tag']}",
    }
    assert all(row["user_id"] == fixture["normal"].id for row in body["data"])

    first_page = await async_client.get(
        PREFIX, params={"page": 1, "page_size": 1}, headers=auth_headers,
    )
    assert first_page.json()["total"] == 3
    assert len(first_page.json()["data"]) == 1
    too_large = await async_client.get(
        PREFIX, params={"page_size": 101}, headers=auth_headers,
    )
    assert too_large.status_code == 422


async def test_cross_user_mark_read_is_404_and_does_not_mutate(
    async_client, auth_headers, async_db_session, notification_fixture
):
    fixture = notification_fixture
    target = fixture["rows"][0]
    target_id = target.id

    denied = await async_client.post(f"{PREFIX}/{target_id}/read", headers=auth_headers)
    assert denied.status_code == 404
    await async_db_session.refresh(target)
    assert target.is_read is False

    app.dependency_overrides[get_current_user_id] = lambda: fixture["normal"].id
    try:
        first = await async_client.post(f"{PREFIX}/{target_id}/read", headers=auth_headers)
        second = await async_client.post(f"{PREFIX}/{target_id}/read", headers=auth_headers)
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)
    assert first.status_code == second.status_code == 200
    await async_db_session.refresh(target)
    assert target.is_read is True


async def test_read_all_only_marks_current_user(
    async_client, auth_headers, async_db_session, notification_fixture, as_user
):
    fixture = notification_fixture
    as_user(fixture["normal"].id)
    response = await async_client.post(f"{PREFIX}/read-all", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["marked_count"] == 2

    for row in fixture["rows"][:3]:
        await async_db_session.refresh(row)
        assert row.is_read is True
    await async_db_session.refresh(fixture["rows"][3])
    assert fixture["rows"][3].is_read is False, "read-all 不得越过当前用户"
