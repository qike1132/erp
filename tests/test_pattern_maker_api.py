"""版师管理 API：CRUD、权限、唯一约束及项目删除联动。"""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fastapi_app.core.deps import _get_user_with_permissions
from fastapi_app.main import app
from fastapi_app.services import pattern_maker_service
from fastapi_app.shared_models import CustomerSamplingProject, PatternMaker, User

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]
PREFIX = "/api/v1/pattern-maker/pattern-makers"


async def test_pattern_maker_crud_validation_and_delete_linkage(
    async_client, auth_headers, async_db_session
):
    tag = uuid4().hex[:8]
    name_b = f"版师B-{tag}"
    name_a = f"版师A-{tag}"
    created_b = await async_client.post(PREFIX, json={"name": name_b}, headers=auth_headers)
    created_a = await async_client.post(PREFIX, json={"name": name_a}, headers=auth_headers)
    assert created_b.status_code == created_a.status_code == 200
    maker_id = created_a.json()["id"]

    listed = await async_client.get(PREFIX, headers=auth_headers)
    names = [row["name"] for row in listed.json()["items"] if tag in row["name"]]
    assert names == sorted([name_a, name_b])

    duplicate = await async_client.post(PREFIX, json={"name": f"  {name_a}  "}, headers=auth_headers)
    assert duplicate.status_code == 400
    assert "已存在" in duplicate.json()["detail"]
    assert (await async_client.post(PREFIX, json={"name": ""}, headers=auth_headers)).status_code == 422
    assert (await async_client.post(PREFIX, json={"name": "   "}, headers=auth_headers)).status_code == 400
    assert (await async_client.post(PREFIX, json={"name": "名" * 101}, headers=auth_headers)).status_code == 422

    project = CustomerSamplingProject(
        sequence_no=f"PM-{tag}",
        product_name=f"版师联动产品-{tag}",
        pattern_maker_id=maker_id,
        pattern_maker_name=name_a,
    )
    async_db_session.add(project)
    await async_db_session.flush()

    deleted = await async_client.delete(f"{PREFIX}/{maker_id}", headers=auth_headers)
    assert deleted.status_code == 200, deleted.text
    await async_db_session.refresh(project)
    assert project.pattern_maker_id is None
    assert project.pattern_maker_name is None
    assert (await async_client.delete(f"{PREFIX}/{maker_id}", headers=auth_headers)).status_code == 404


async def test_pattern_maker_requires_manage_permission(async_client, auth_headers):
    user = User(username="no-pattern-manage", password="x", is_super=False, status=True)
    user.permissions = []

    async def override_user():
        return user

    app.dependency_overrides[_get_user_with_permissions] = override_user
    try:
        response = await async_client.post(
            PREFIX, json={"name": f"无权限-{uuid4().hex[:8]}"}, headers=auth_headers,
        )
    finally:
        app.dependency_overrides.pop(_get_user_with_permissions, None)
    assert response.status_code == 403


async def test_concurrent_create_same_name_is_unique(async_db_session, test_engine):
    """应用层查重之外，数据库唯一约束也必须兜住真实并发。"""
    name = f"并发版师-{uuid4().hex[:8]}"
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def create():
        async with factory() as session:
            async with session.begin():
                return await pattern_maker_service.create_pattern_maker(session, name)

    first, second = await asyncio.gather(create(), create(), return_exceptions=True)
    assert [type(value) for value in (first, second)].count(dict) == 1
    assert any(isinstance(value, Exception) for value in (first, second))
    count = await async_db_session.scalar(
        select(func.count()).select_from(PatternMaker).where(PatternMaker.name == name)
    )
    assert count == 1
