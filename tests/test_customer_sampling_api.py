"""按客户分类打样信息模块 API 端点集成测试

测试范围：22 个端点的正常路径与异常路径（404/409/400）

策略：
- 使用 httpx AsyncClient + ASGITransport 连接 FastAPI app
- override 依赖：get_async_db / get_async_read_db 用事务隔离的测试 session
- override 权限依赖：get_current_user_id / _get_user_with_permissions 返回 mock 用户
- 主库 + 外层事务回滚隔离，测试间不污染数据库

对应需求规格：.codeartsdoer/specs/customer_sampling/spec.md
对应技术设计：.codeartsdoer/specs/customer_sampling/design.md
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# 测试专用数据库（conftest 计算得出，与开发库 erp_system 隔离，避免种子数据污染）
from conftest import TEST_DATABASE_URL

# API 前缀
API_PREFIX = "/api/v1/pattern-room"


@pytest_asyncio.fixture
async def cs_api():
    """API 测试客户端 + 事务隔离 db session + 权限 override

    Yields:
        (client, db): httpx AsyncClient 与事务隔离的 AsyncSession
    """
    from fastapi_app.core.database import get_async_db, get_async_read_db
    from fastapi_app.core.deps import _get_user_with_permissions, get_current_user_id
    from fastapi_app.main import app
    from fastapi_app.shared_models import Base

    # 让 app 的全局引擎在当前测试 loop 上按 conftest 重定向后的 URL 重建：
    # 本套件只 override 请求依赖，而 create_project 会经
    # numbering_sequence.allocate_sequence 直接引用 _AsyncSessionLocal（非请求路径），
    # 不先跑守卫的话该引用为 None → TypeError。
    from fastapi_app.core import database as _db_mod
    await _db_mod.ensure_engine_for_current_loop()

    engine = create_async_engine(TEST_DATABASE_URL, echo=False, pool_pre_ping=True)
    try:
        # 确保表存在（幂等）
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with engine.connect() as conn:
            trans = await conn.begin()
            # 每个请求独立 session（共享 connection + 外层事务），
            # join_transaction_mode="create_savepoint"：session 在外层事务内用 SAVEPOINT，
            # db_transaction 的 commit/rollback 只影响该请求的 SAVEPOINT，外层 trans 保持，
            # 测试结束 trans.rollback() 统一回滚所有数据。
            async def override_db():
                async with AsyncSession(
                    bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint",
                ) as s:
                    yield s

            # 共享 session 用于测试内直接查询验证
            shared_session = AsyncSession(
                bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint",
            )
            try:
                # ---- 依赖 override ----
                async def override_user_id():
                    return None  # 避免 created_by 外键约束（主库无对应 user 记录）

                async def override_user_with_perms():
                    user = MagicMock()
                    user.id = None  # 避免 created_by/operator_id 外键约束
                    user.username = "admin"
                    user.is_super = True
                    user.has_permission = MagicMock(return_value=True)
                    return user

                original_overrides = dict(app.dependency_overrides)
                app.dependency_overrides[get_async_db] = override_db
                app.dependency_overrides[get_async_read_db] = override_db
                app.dependency_overrides[get_current_user_id] = override_user_id
                app.dependency_overrides[_get_user_with_permissions] = override_user_with_perms

                transport = ASGITransport(app=app)
                # Bearer token + Origin 绕过 CSRF 中间件（中间件仅校验 Bearer 存在性与 Origin 白名单）
                async with AsyncClient(
                    transport=transport,
                    base_url="http://test",
                    headers={
                        "Authorization": "Bearer test-token",
                        "Origin": "http://localhost:3000",
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


async def _create_project_via_api(client, product_name="API测试产品", pattern_maker_id=None, remark=None):
    """通过 API 创建项目，返回 (project_id, sequence_no)"""
    payload = {"product_name": product_name}
    if pattern_maker_id is not None:
        payload["pattern_maker_id"] = pattern_maker_id
    if remark is not None:
        payload["remark"] = remark
    resp = await client.post(f"{API_PREFIX}/projects", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    return data["id"], data.get("sequence_no")


@pytest.mark.integration
class TestCustomerSamplingApi:
    """按客户分类打样信息模块 API 端点集成测试"""

    # ==================== 1. 按客户分组聚合查询 ====================

    async def test_grouped_list_empty(self, cs_api):
        """GET /grouped-list 空数据"""
        client, _ = cs_api
        resp = await client.get(f"{API_PREFIX}/grouped-list")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["groups"] == []
        assert data["total_projects"] == 0

    async def test_grouped_list_with_projects(self, cs_api):
        """GET /grouped-list 含项目数据"""
        client, _ = cs_api
        await _create_project_via_api(client, "分组产品1")
        await _create_project_via_api(client, "分组产品2")

        resp = await client.get(f"{API_PREFIX}/grouped-list")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_projects"] == 2
        # 未分类分组
        assert len(data["groups"]) == 1
        assert data["groups"][0]["pattern_maker_name"] == "未分类"

    async def test_grouped_list_keyword(self, cs_api):
        """GET /grouped-list 关键词搜索"""
        client, _ = cs_api
        await _create_project_via_api(client, "毛绒玩具A")
        await _create_project_via_api(client, "其他产品")

        resp = await client.get(f"{API_PREFIX}/grouped-list", params={"keyword": "毛绒"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_projects"] == 1

    async def test_grouped_list_default_in_progress(self, cs_api):
        """GET /grouped-list status 缺省默认只返回进行中项目（前端漏传状态时的兜底）"""
        client, _ = cs_api
        pid_done, _ = await _create_project_via_api(client, "兜底已完成")
        pid_active, _ = await _create_project_via_api(client, "兜底进行中")
        resp = await client.put(
            f"{API_PREFIX}/projects/{pid_done}/status",
            json={"status": "completed"},
        )
        assert resp.status_code == 200

        # 不传 status：只返回进行中项目
        resp = await client.get(f"{API_PREFIX}/grouped-list")
        assert resp.status_code == 200
        data = resp.json()
        projects = [p for g in data["groups"] for p in g["projects"]]
        assert all(p["status"] == "in_progress" for p in projects)
        assert all(p["id"] != pid_done for p in projects)
        assert any(p["id"] == pid_active for p in projects)

        # 显式 status=all：返回全部状态项目
        resp_all = await client.get(f"{API_PREFIX}/grouped-list", params={"status": "all"})
        assert resp_all.status_code == 200
        assert resp_all.json()["total_projects"] == 2

    # ==================== 2. 打样项目列表 ====================

    async def test_list_projects(self, cs_api):
        """GET /projects 分页列表"""
        client, _ = cs_api
        await _create_project_via_api(client, "列表产品1")
        await _create_project_via_api(client, "列表产品2")

        resp = await client.get(f"{API_PREFIX}/projects", params={"page": 1, "per_page": 20})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["total"] == 2
        assert len(data["items"]) == 2

    async def test_list_projects_pagination(self, cs_api):
        """GET /projects 分页边界"""
        client, _ = cs_api
        for i in range(3):
            await _create_project_via_api(client, f"分页产品{i}")

        resp = await client.get(f"{API_PREFIX}/projects", params={"page": 1, "per_page": 2})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["items"]) == 2
        assert data["pages"] == 2

    async def test_list_projects_default_in_progress(self, cs_api):
        """GET /projects status 缺省默认只返回进行中项目（与 grouped-list 一致）"""
        client, _ = cs_api
        pid_done, _ = await _create_project_via_api(client, "列表兜底已完成")
        pid_active, _ = await _create_project_via_api(client, "列表兜底进行中")
        resp = await client.put(
            f"{API_PREFIX}/projects/{pid_done}/status",
            json={"status": "completed"},
        )
        assert resp.status_code == 200

        # 不传 status：只返回进行中项目
        resp = await client.get(f"{API_PREFIX}/projects")
        assert resp.status_code == 200
        data = resp.json()
        assert all(item["status"] == "in_progress" for item in data["items"])
        assert all(item["id"] != pid_done for item in data["items"])
        assert any(item["id"] == pid_active for item in data["items"])

        # 显式 status=all：返回全部状态项目
        resp_all = await client.get(f"{API_PREFIX}/projects", params={"status": "all"})
        assert resp_all.status_code == 200
        assert resp_all.json()["total"] == 2

    # ==================== 3. 打样项目详情 ====================

    async def test_get_project_detail(self, cs_api):
        """GET /projects/{id} 正常"""
        client, _ = cs_api
        pid, seq = await _create_project_via_api(client, "详情产品")

        resp = await client.get(f"{API_PREFIX}/projects/{pid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == pid
        assert data["sequence_no"] == seq
        assert data["product_name"] == "详情产品"
        assert data["current_version"] == "T1"
        assert len(data["versions"]) == 1
        assert data["versions"][0]["version_no"] == "T1"

    async def test_get_project_detail_not_found(self, cs_api):
        """GET /projects/{id} 不存在 → 404"""
        client, _ = cs_api
        resp = await client.get(f"{API_PREFIX}/projects/99999")
        assert resp.status_code == 404

    # ==================== 4. 新增打样项目 ====================

    async def test_create_project(self, cs_api):
        """POST /projects 正常创建"""
        client, _ = cs_api
        resp = await client.post(
            f"{API_PREFIX}/projects",
            json={"product_name": "新建产品", "remark": "测试备注"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["sequence_no"].startswith("CS-")
        assert "id" in data

    async def test_create_project_missing_name(self, cs_api):
        """POST /projects 缺少产品名 → 422（Pydantic 校验）"""
        client, _ = cs_api
        resp = await client.post(f"{API_PREFIX}/projects", json={})
        assert resp.status_code == 422

    async def test_create_project_empty_name(self, cs_api):
        """POST /projects 空产品名 → 422"""
        client, _ = cs_api
        resp = await client.post(f"{API_PREFIX}/projects", json={"product_name": ""})
        assert resp.status_code == 422

    # ==================== 5. 编辑打样项目 ====================

    async def test_update_project(self, cs_api):
        """PUT /projects/{id} 正常编辑"""
        client, _ = cs_api
        pid, _ = await _create_project_via_api(client, "编辑前")

        # 获取当前 version
        detail = (await client.get(f"{API_PREFIX}/projects/{pid}")).json()
        version = detail["version"]

        resp = await client.put(
            f"{API_PREFIX}/projects/{pid}",
            json={"product_name": "编辑后", "version": version},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # 验证更新
        detail2 = (await client.get(f"{API_PREFIX}/projects/{pid}")).json()
        assert detail2["product_name"] == "编辑后"

    async def test_update_project_optimistic_lock(self, cs_api):
        """PUT /projects/{id} 乐观锁冲突 → 409"""
        client, _ = cs_api
        pid, _ = await _create_project_via_api(client, "锁冲突测试")
        detail = (await client.get(f"{API_PREFIX}/projects/{pid}")).json()
        version = detail["version"]

        # 用错误 version
        resp = await client.put(
            f"{API_PREFIX}/projects/{pid}",
            json={"product_name": "冲突", "version": version + 100},
        )
        assert resp.status_code == 409

    async def test_update_project_not_found(self, cs_api):
        """PUT /projects/{id} 不存在 → 404"""
        client, _ = cs_api
        resp = await client.put(
            f"{API_PREFIX}/projects/99999",
            json={"product_name": "x", "version": 0},
        )
        assert resp.status_code == 404

    # ==================== 5b. 更新项目状态 ====================

    async def test_update_project_status(self, cs_api):
        """PUT /projects/{id}/status 置为已完成，分组摘要返回 status"""
        client, _ = cs_api
        pid, _ = await _create_project_via_api(client, "状态API测试")

        resp = await client.put(
            f"{API_PREFIX}/projects/{pid}/status",
            json={"status": "completed"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # 详情与分组摘要均带 completed（分组接口 status 缺省默认只返回进行中，此处显式传 status=all 才能看到已完成项目）
        detail = (await client.get(f"{API_PREFIX}/projects/{pid}")).json()
        assert detail["status"] == "completed"
        grouped = (await client.get(f"{API_PREFIX}/grouped-list", params={"status": "all"})).json()
        summary = next(
            p for g in grouped["groups"] for p in g["projects"] if p["id"] == pid
        )
        assert summary["status"] == "completed"

    async def test_update_project_status_invalid(self, cs_api):
        """PUT /projects/{id}/status 非法状态 → 422"""
        client, _ = cs_api
        pid, _ = await _create_project_via_api(client, "状态API非法测试")
        resp = await client.put(
            f"{API_PREFIX}/projects/{pid}/status",
            json={"status": "unknown"},
        )
        assert resp.status_code == 422

    async def test_update_project_status_not_found(self, cs_api):
        """PUT /projects/{id}/status 项目不存在 → 404"""
        client, _ = cs_api
        resp = await client.put(
            f"{API_PREFIX}/projects/99999/status",
            json={"status": "completed"},
        )
        assert resp.status_code == 404

    # ==================== 5b. 已完成项目列表状态筛选 ====================

    async def test_list_projects_status_filter(self, cs_api):
        """GET /projects?status=completed 只返回已完成项目"""
        client, _ = cs_api
        pid, _ = await _create_project_via_api(client, "筛选已完成A")
        pid_b, _ = await _create_project_via_api(client, "筛选进行中B")
        # 将 pid 标记为完成
        resp = await client.put(
            f"{API_PREFIX}/projects/{pid}/status",
            json={"status": "completed"},
        )
        assert resp.status_code == 200

        resp = await client.get(
            f"{API_PREFIX}/projects", params={"status": "completed"},
        )
        assert resp.status_code == 200
        data = resp.json()
        # 断言返回的都是已完成项目
        assert all(item["status"] == "completed" for item in data["items"])
        # 断言我们标记完成的项目在结果中，且 completed_at 已写入
        target = next((item for item in data["items"] if item["id"] == pid), None)
        assert target is not None
        assert target["completed_at"] is not None
        # 未完成的项目不应出现
        assert all(item["id"] != pid_b for item in data["items"])

    # 5c. 已完成项目表格查询（GET /projects/completed-table）：
    # 该端点已随板房重构移除（后端无此路由，前端 patternRoom.ts 也改用
    # GET /projects?status=completed，由 test_list_projects_status_filter 覆盖），
    # 原 3 个 completed_table_* 用例删除，避免误将请求落入 /projects/{project_id}。

    # ==================== 6. 删除打样项目 ====================

    async def test_delete_project(self, cs_api):
        """DELETE /projects/{id} 正常删除"""
        client, _ = cs_api
        pid, _ = await _create_project_via_api(client, "待删除")

        resp = await client.delete(f"{API_PREFIX}/projects/{pid}")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # 验证已删除
        resp2 = await client.get(f"{API_PREFIX}/projects/{pid}")
        assert resp2.status_code == 404

    async def test_delete_project_not_found(self, cs_api):
        """DELETE /projects/{id} 不存在 → 404"""
        client, _ = cs_api
        resp = await client.delete(f"{API_PREFIX}/projects/99999")
        assert resp.status_code == 404

    # ==================== 7. 部位列表 ====================

    async def test_list_parts_empty(self, cs_api):
        """GET /projects/{id}/parts 空部位"""
        client, _ = cs_api
        pid, _ = await _create_project_via_api(client, "空部位产品")

        resp = await client.get(f"{API_PREFIX}/projects/{pid}/parts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []

    async def test_list_parts_project_not_found(self, cs_api):
        """GET /projects/{id}/parts 项目不存在 → 404"""
        client, _ = cs_api
        resp = await client.get(f"{API_PREFIX}/projects/99999/parts")
        assert resp.status_code == 404

    # ==================== 8. 新增部位 ====================

    async def test_create_part(self, cs_api):
        """POST /projects/{id}/parts 正常新增"""
        client, _ = cs_api
        pid, _ = await _create_project_via_api(client, "部位产品")

        resp = await client.post(
            f"{API_PREFIX}/projects/{pid}/parts",
            json={
                "part_name": "身体",
                "sort_order": 1,
                "fabric_name": "绒布",
                "fabric_spec": "100g",
                "unit_price": 10.5,
                "delivery_days": 7,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # 验证
        parts = (await client.get(f"{API_PREFIX}/projects/{pid}/parts")).json()
        assert len(parts["items"]) == 1
        assert parts["items"][0]["part_name"] == "身体"
        assert parts["items"][0]["fabric_name"] == "绒布"

    async def test_create_part_duplicate_name(self, cs_api):
        """POST /projects/{id}/parts 部位名重复 → 400"""
        client, _ = cs_api
        pid, _ = await _create_project_via_api(client, "重复部位产品")
        await client.post(f"{API_PREFIX}/projects/{pid}/parts", json={"part_name": "身体"})

        resp = await client.post(f"{API_PREFIX}/projects/{pid}/parts", json={"part_name": "身体"})
        assert resp.status_code == 400

    async def test_create_part_project_not_found(self, cs_api):
        """POST /projects/{id}/parts 项目不存在 → 404"""
        client, _ = cs_api
        resp = await client.post(f"{API_PREFIX}/projects/99999/parts", json={"part_name": "身体"})
        assert resp.status_code == 404

    # ==================== 9. 编辑部位 ====================

    async def test_update_part(self, cs_api):
        """PUT /parts/{id} 正常编辑"""
        client, _ = cs_api
        pid, _ = await _create_project_via_api(client, "编辑部位产品")
        await client.post(f"{API_PREFIX}/projects/{pid}/parts", json={"part_name": "身体", "fabric_name": "绒布"})

        parts = (await client.get(f"{API_PREFIX}/projects/{pid}/parts")).json()
        part = parts["items"][0]

        resp = await client.put(
            f"{API_PREFIX}/parts/{part['id']}",
            json={"fabric_name": "棉布", "version": part["version"]},
        )
        assert resp.status_code == 200

        parts2 = (await client.get(f"{API_PREFIX}/projects/{pid}/parts")).json()
        assert parts2["items"][0]["fabric_name"] == "棉布"

    async def test_update_part_optimistic_lock(self, cs_api):
        """PUT /parts/{id} 乐观锁冲突 → 409"""
        client, _ = cs_api
        pid, _ = await _create_project_via_api(client, "部位锁冲突")
        await client.post(f"{API_PREFIX}/projects/{pid}/parts", json={"part_name": "身体"})
        parts = (await client.get(f"{API_PREFIX}/projects/{pid}/parts")).json()
        part = parts["items"][0]

        resp = await client.put(
            f"{API_PREFIX}/parts/{part['id']}",
            json={"fabric_name": "棉布", "version": part["version"] + 100},
        )
        assert resp.status_code == 409

    async def test_update_part_not_found(self, cs_api):
        """PUT /parts/{id} 不存在 → 404"""
        client, _ = cs_api
        resp = await client.put(f"{API_PREFIX}/parts/99999", json={"version": 0})
        assert resp.status_code == 404

    # ==================== 10. 删除部位 ====================

    async def test_delete_part(self, cs_api):
        """DELETE /parts/{id} 正常删除"""
        client, _ = cs_api
        pid, _ = await _create_project_via_api(client, "删除部位产品")
        await client.post(f"{API_PREFIX}/projects/{pid}/parts", json={"part_name": "身体"})
        parts = (await client.get(f"{API_PREFIX}/projects/{pid}/parts")).json()
        part_id = parts["items"][0]["id"]

        resp = await client.delete(f"{API_PREFIX}/parts/{part_id}")
        assert resp.status_code == 200

        parts2 = (await client.get(f"{API_PREFIX}/projects/{pid}/parts")).json()
        assert len(parts2["items"]) == 0

    async def test_delete_part_not_found(self, cs_api):
        """DELETE /parts/{id} 不存在 → 404"""
        client, _ = cs_api
        resp = await client.delete(f"{API_PREFIX}/parts/99999")
        assert resp.status_code == 404

    # ==================== 11. 版本列表 ====================

    async def test_list_versions(self, cs_api):
        """GET /projects/{id}/versions 版本列表"""
        client, _ = cs_api
        pid, _ = await _create_project_via_api(client, "版本列表产品")

        resp = await client.get(f"{API_PREFIX}/projects/{pid}/versions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["version_no"] == "T1"

    async def test_list_versions_project_not_found(self, cs_api):
        """GET /projects/{id}/versions 项目不存在 → 404"""
        client, _ = cs_api
        resp = await client.get(f"{API_PREFIX}/projects/99999/versions")
        assert resp.status_code == 404

    # ==================== 12. 版本详情 ====================

    async def test_get_version_detail_t1(self, cs_api):
        """GET /versions/{id} T1 基线版本"""
        client, _ = cs_api
        pid, _ = await _create_project_via_api(client, "T1详情产品")
        versions = (await client.get(f"{API_PREFIX}/projects/{pid}/versions")).json()
        t1_id = versions["items"][0]["id"]

        resp = await client.get(f"{API_PREFIX}/versions/{t1_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version_no"] == "T1"
        assert data["is_baseline"] is True
        assert data["full_snapshot"] == []
        assert data["change_summary"] is None

    async def test_get_version_detail_t2(self, cs_api):
        """GET /versions/{id} T2 变更版本（直接落库种子：创建版本接口已随功能移除）"""
        from sqlalchemy import select

        from fastapi_app.shared_models import CustomerSamplingFabricVersion, CustomerSamplingRole

        client, db = cs_api
        pid, _ = await _create_project_via_api(client, "T2详情产品")
        await client.post(f"{API_PREFIX}/projects/{pid}/parts", json={"part_name": "身体", "fabric_name": "绒布"})

        role = (await db.execute(
            select(CustomerSamplingRole).where(CustomerSamplingRole.project_id == pid)
        )).scalars().first()
        v2 = CustomerSamplingFabricVersion(
            project_id=pid,
            role_id=role.id,
            version_no="T2",
            snapshot_data=[{"part_name": "身体", "fabric_name": "绒布"}],
            change_summary=[{"change_type": "add", "part_name": "身体"}],
        )
        db.add(v2)
        await db.flush()

        resp = await client.get(f"{API_PREFIX}/versions/{v2.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version_no"] == "T2"
        assert data["is_baseline"] is False
        assert data["full_snapshot"] is None
        assert data["change_summary"] is not None
        assert len(data["change_summary"]) == 1
        assert data["change_summary"][0]["change_type"] == "add"

    async def test_get_version_detail_not_found(self, cs_api):
        """GET /versions/{id} 不存在 → 404"""
        client, _ = cs_api
        resp = await client.get(f"{API_PREFIX}/versions/99999")
        assert resp.status_code == 404

    # ==================== 13. 变更日志 ====================

    async def test_list_change_logs(self, cs_api):
        """GET /projects/{id}/change-logs 变更日志"""
        client, _ = cs_api
        pid, _ = await _create_project_via_api(client, "日志产品")

        resp = await client.get(f"{API_PREFIX}/projects/{pid}/change-logs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        actions = [log["action"] for log in data["items"]]
        assert "create_project" in actions

    async def test_list_change_logs_project_not_found(self, cs_api):
        """GET /projects/{id}/change-logs 项目不存在 → 404"""
        client, _ = cs_api
        resp = await client.get(f"{API_PREFIX}/projects/99999/change-logs")
        assert resp.status_code == 404

    # ==================== 15. 上传产品图片 ====================

    async def test_upload_image_unsupported_type(self, cs_api):
        """POST /projects/{id}/image 不支持格式 → 400"""
        client, _ = cs_api
        pid, _ = await _create_project_via_api(client, "图片产品")

        resp = await client.post(
            f"{API_PREFIX}/projects/{pid}/image",
            files={"file": ("test.gif", b"GIF89a", "image/gif")},
        )
        assert resp.status_code == 400

    async def test_upload_image_project_not_found(self, cs_api):
        """POST /projects/{id}/image 项目不存在 → 404"""
        client, _ = cs_api
        resp = await client.post(
            f"{API_PREFIX}/projects/99999/image",
            files={"file": ("test.png", b"\x89PNG", "image/png")},
        )
        assert resp.status_code == 404

    # ==================== 完整业务流程 ====================

    async def test_full_workflow(self, cs_api):
        """完整业务流程：创建项目 → 新增部位 → 查询版本 → 变更日志"""
        from sqlalchemy import select

        from fastapi_app.shared_models import CustomerSamplingFabricVersion, CustomerSamplingRole

        client, db = cs_api

        # 1. 创建项目
        pid, seq = await _create_project_via_api(client, "完整流程产品", remark="E2E测试")
        assert seq.startswith("CS-")

        # 2. 新增部位
        resp = await client.post(
            f"{API_PREFIX}/projects/{pid}/parts",
            json={"part_name": "身体", "fabric_name": "绒布", "unit_price": 10, "sort_order": 1},
        )
        assert resp.status_code == 200

        # 3. 直接落库 T2 版本快照（创建版本接口已随功能移除）
        role = (await db.execute(
            select(CustomerSamplingRole).where(CustomerSamplingRole.project_id == pid)
        )).scalars().first()
        v2 = CustomerSamplingFabricVersion(
            project_id=pid,
            role_id=role.id,
            version_no="T2",
            snapshot_data=[{"part_name": "身体", "fabric_name": "绒布"}],
            change_summary=[{"change_type": "add", "part_name": "身体"}],
            reason="首次打样",
        )
        db.add(v2)
        await db.flush()

        # 4. 查询 T2 diff
        detail = await client.get(f"{API_PREFIX}/versions/{v2.id}")
        assert detail.status_code == 200
        diff_data = detail.json()
        assert diff_data["change_summary"] is not None
        assert diff_data["change_summary"][0]["change_type"] == "add"

        # 5. 变更日志应记录 create_project / create_part
        logs = await client.get(f"{API_PREFIX}/projects/{pid}/change-logs")
        assert logs.status_code == 200
        actions = {log["action"] for log in logs.json()["items"]}
        assert "create_project" in actions
        assert "create_part" in actions

        # 6. 分组查询应包含该项目
        grouped = await client.get(f"{API_PREFIX}/grouped-list")
        assert grouped.status_code == 200
        assert grouped.json()["total_projects"] >= 1
