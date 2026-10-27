"""按客户分类打样信息模块 —— 部位字段历史候选取值（service + API 双层）

背景：板房录入页 /pattern-room 的「供应商」「布料名称」是自由文本，重复率高。
新增只读取值端点 GET /pattern-room/part-field-candidates 把板房历史已录值
去重后返回，前端做成 combobox 减少重复手输。

本套件覆盖两层：
- service 层 mock：归并逻辑（trim + 大小写归并 + count 累加 + 输出值 trim + 排序 + limit 截断）
- API 层集成（cs_api fixture，savepoint 事务隔离可写数据）：真实造项目+部位后请求
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

# 项目根目录入 path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# 测试专用数据库（与开发库 erp_system 隔离）
from conftest import TEST_DATABASE_URL

from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import (
    _get_user_with_permissions,
    get_current_user_id,
    get_current_user_id_write_strict,
)
from fastapi_app.main import app
from fastapi_app.services.customer_sampling_service import get_part_field_candidates

API_PREFIX = "/api/v1/pattern-room"


def _mock_rows(rows):
    """构造 mock db.execute 返回值 —— 模拟 `for value, count in result.all()` 解包。

    不复用 tests/test_customer_sampling_service.py 的 _mock_result：
    那个只配 scalar_one_or_none/scalars().all()/first()，没配 .all()，
    本场景直接 .all() 解包 tuple，用裸 MagicMock 更稳。
    """
    mr = MagicMock()
    mr.all.return_value = rows
    return mr


# ============================================================
# service 层 mock 测试：归并逻辑
# ============================================================

class TestGetPartFieldCandidatesService:
    """get_part_field_candidates 的归并 / 排序 / limit 逻辑（mock db）"""

    @pytest.mark.asyncio
    async def test_trim_and_case_merges_variants(self, mock_async_db):
        """「merida」「 merida 」「MERIDA」三种变体（空格+大小写）归并成一条，count 累加，展示取高频写法"""
        mock_async_db.execute = AsyncMock(return_value=_mock_rows([
            ('merida', 10), (' merida ', 5), ('MERIDA', 7),
        ]))
        result = await get_part_field_candidates(
            mock_async_db, fields=('supplier_name',), limit=50,
        )
        items = result['fields']['supplier_name']
        assert len(items) == 1
        assert items[0]['value'] == 'merida'  # 单变体最高频（10）胜出
        assert items[0]['count'] == 22  # 10+5+7

    @pytest.mark.asyncio
    async def test_empty_and_whitespace_strings_skipped(self, mock_async_db):
        """空串和纯空格串不出现"""
        mock_async_db.execute = AsyncMock(return_value=_mock_rows([
            ('', 10), ('   ', 5), ('美利达', 3),
        ]))
        result = await get_part_field_candidates(
            mock_async_db, fields=('supplier_name',), limit=50,
        )
        items = result['fields']['supplier_name']
        assert len(items) == 1
        assert items[0]['value'] == '美利达'

    @pytest.mark.asyncio
    async def test_output_value_is_trimmed(self, mock_async_db):
        """输出值本身也 trim：不会把手输的空格变体回填到前端"""
        mock_async_db.execute = AsyncMock(return_value=_mock_rows([
            ('  美利达  ', 5),
        ]))
        result = await get_part_field_candidates(
            mock_async_db, fields=('supplier_name',), limit=50,
        )
        items = result['fields']['supplier_name']
        assert items[0]['value'] == '美利达'
        assert items[0]['count'] == 5

    @pytest.mark.asyncio
    async def test_sorted_by_count_desc_then_value_asc(self, mock_async_db):
        """排序：count 降序，count 相同按 value 升序"""
        mock_async_db.execute = AsyncMock(return_value=_mock_rows([
            ('B供应商', 3), ('A供应商', 3), ('C供应商', 7),
        ]))
        result = await get_part_field_candidates(
            mock_async_db, fields=('supplier_name',), limit=50,
        )
        items = result['fields']['supplier_name']
        values = [it['value'] for it in items]
        assert values == ['C供应商', 'A供应商', 'B供应商']

    @pytest.mark.asyncio
    async def test_limit_applied_after_merge(self, mock_async_db):
        """limit 截断发生在归并之后：variant 多的真值不会因 SQL 先 limit 被挤出"""
        # 构造：'merida' 有 4 个 variant（合计 35 次），另一个供应商只有 6 次
        # 归并后 merida=35 排第一，limit=2 时它必须出现
        mock_async_db.execute = AsyncMock(return_value=_mock_rows([
            ('merida', 20), (' merida ', 8), ('MERIDA', 5), ('Merida', 2),
            ('某某厂', 6),
        ]))
        result = await get_part_field_candidates(
            mock_async_db, fields=('supplier_name',), limit=2,
        )
        items = result['fields']['supplier_name']
        assert len(items) == 2
        assert items[0]['value'] == 'merida'
        assert items[0]['count'] == 35  # 20+8+5+2


# ============================================================
# API 层集成测试
# ============================================================

@pytest_asyncio.fixture
async def cs_api():
    """API 测试客户端 + 事务隔离 db session + 权限 override（同 test_customer_sampling_api 模式）"""
    from fastapi_app.core import database as _db_mod
    from fastapi_app.shared_models import Base
    await _db_mod.ensure_engine_for_current_loop()

    engine = create_async_engine(TEST_DATABASE_URL, echo=False, pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with engine.connect() as conn:
            trans = await conn.begin()
            async def override_db():
                async with AsyncSession(
                    bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint",
                ) as s:
                    yield s

            shared_session = AsyncSession(
                bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint",
            )
            try:
                async def override_user_id():
                    return None

                async def override_user_with_perms():
                    user = MagicMock()
                    user.id = None
                    user.username = "admin"
                    user.is_super = True
                    user.has_permission = MagicMock(return_value=True)
                    return user

                original_overrides = dict(app.dependency_overrides)
                app.dependency_overrides[get_async_db] = override_db
                app.dependency_overrides[get_async_read_db] = override_db
                app.dependency_overrides[get_current_user_id] = override_user_id
                app.dependency_overrides[get_current_user_id_write_strict] = override_user_id
                app.dependency_overrides[_get_user_with_permissions] = override_user_with_perms

                transport = ASGITransport(app=app)
                async with AsyncClient(
                    transport=transport,
                    base_url="http://test",
                    cookies={"fastapi_csrf_token": "test-csrf-token"},
                    headers={
                        "Authorization": "Bearer test-token",
                        "Origin": "http://localhost:3000",
                        # F-BE-CORE-07 收口后「Bearer+Cookie」请求必须过 double-submit
                        # （cookie 与 header 同值即可通过 compare_digest）
                        "X-CSRF-Token": "test-csrf-token",
                    },
                ) as client:
                    try:
                        yield client, shared_session
                    finally:
                        app.dependency_overrides.clear()
                        app.dependency_overrides.update(original_overrides)

                await shared_session.close()
            finally:
                await trans.rollback()
    finally:
        await engine.dispose()


@pytest.mark.integration
class TestPartFieldCandidatesApi:
    """GET /pattern-room/part-field-candidates 端到端（真实造数据）"""

    async def _create_project(self, client, name):
        resp = await client.post(f"{API_PREFIX}/projects", json={"product_name": name})
        assert resp.status_code == 200, resp.text
        return resp.json()["id"]

    async def _create_part(self, client, project_id, part_name, supplier_name=None, fabric_name=None):
        """经批量新增端点造部位（前端录入框走的就是这条路径，supplier_name 是自由文本）"""
        item = {"part_name": part_name}
        if supplier_name is not None:
            item["supplier_name"] = supplier_name
        if fabric_name is not None:
            item["fabric_name"] = fabric_name
        resp = await client.post(
            f"{API_PREFIX}/projects/{project_id}/parts/batch", json={"items": [item]},
        )
        assert resp.status_code == 200, resp.text

    @pytest.mark.asyncio
    async def test_merida_appears_in_candidates(self, cs_api):
        """录过供应商「美利达」（含空格变体），候选中出现 trim 后的「美利达」，count 为变体合计"""
        client, _ = cs_api
        pid = await self._create_project(client, "候选测试产品A")
        await self._create_part(client, pid, "身体", supplier_name="美利达")
        await self._create_part(client, pid, "头部", supplier_name="美利达")
        await self._create_part(client, pid, "袖子", supplier_name=" 美利达 ")

        resp = await client.get(f"{API_PREFIX}/part-field-candidates")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        items = data["fields"]["supplier_name"]
        # 找到 trim 后的「美利达」
        mld = next((it for it in items if it["value"] == "美利达"), None)
        assert mld is not None, f"候选里没有 trim 后的美利达: {items}"
        assert mld["count"] == 3  # 三次使用（两个 '美利达' + 一个 ' 美利达 ' 归并）

    @pytest.mark.asyncio
    async def test_empty_string_excluded(self, cs_api):
        """空串 supplier_name 不出现在候选里"""
        client, _ = cs_api
        pid = await self._create_project(client, "候选测试产品B")
        await self._create_part(client, pid, "身体", supplier_name="")
        await self._create_part(client, pid, "头部", supplier_name="  ")
        await self._create_part(client, pid, "袖子", supplier_name="美利达")

        resp = await client.get(f"{API_PREFIX}/part-field-candidates")
        assert resp.status_code == 200
        items = resp.json()["fields"]["supplier_name"]
        values = [it["value"] for it in items]
        assert "" not in values
        assert "美利达" in values

    @pytest.mark.asyncio
    async def test_fabric_name_field_filter(self, cs_api):
        """fields=fabric_name 时只返回 fabric_name 组，不含 supplier_name 键"""
        client, _ = cs_api
        pid = await self._create_project(client, "候选测试产品C")
        await self._create_part(client, pid, "身体", fabric_name="全棉毛绒布")
        await self._create_part(client, pid, "头部", fabric_name="全棉毛绒布")

        resp = await client.get(
            f"{API_PREFIX}/part-field-candidates", params={"fields": "fabric_name"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "fabric_name" in data["fields"]
        assert "supplier_name" not in data["fields"]
        items = data["fields"]["fabric_name"]
        assert any(it["value"] == "全棉毛绒布" and it["count"] == 2 for it in items)

    @pytest.mark.asyncio
    async def test_unknown_field_returns_422(self, cs_api):
        """未知字段名 → 422，不静默忽略"""
        client, _ = cs_api
        resp = await client.get(
            f"{API_PREFIX}/part-field-candidates", params={"fields": "fabric_color_no"},
        )
        assert resp.status_code == 422
