"""BOM 保存端点·陈旧角色 id → 400 的**端到端**回归测试（真实 HTTP 请求）。

背景
----
``bom_role_resolver.resolve_role_rows`` 对「payload 里的 ``id`` 不属于该产品」抛
``ValueError(f'角色 {rid} 不属于该产品')``（见 bom_role_resolver.py:174-177）；
保存端点 ``api_save_product_bom`` 经 ``db_transaction`` + ``core/exceptions`` 的默认
映射（``ValueError → HTTP 400``，见 exceptions.py:202-204）返回 400。

本用例**不读代码推断**，而是真正发 HTTP 请求打满整条链路：
``TestClient(ASGI) → CSRF 中间件 → 权限依赖 → db_transaction → save_bom → resolve_role_rows``，
断言返回 400 且 detail 含「不属于该产品」与陈旧 id；同时用「合法 payload → 200」做
对照，排除「端点整体 400」的假阳性。

说明：
- 数据库用**真实异步 SQLAlchemy session**（内存 SQLite + ``create_all`` + btrim UDF），
  只覆盖本路径用到的表；不触碰生产库。
- CSRF 通过显式携带允许的 ``Origin`` 头放行（本机 APP_ENV=production，CSRF cookie 以
  Secure 下发，纯 http 测试客户端不会回传，其机理见 test_global_role.py 的
  ``_csrf_origin`` fixture 与本次独立探针结论）。
- 权限依赖 ``require_permission`` → ``_get_user_with_permissions`` **不覆盖**，直接复用
  conftest 自动注入的 ``mock_current_user``（其带 ``has_permission`` 与 ``is_super``）；
  只覆盖 ``get_async_db`` 指向真实 session。
"""
from unittest.mock import AsyncMock, patch

import httpx
import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from fastapi_app.core.database import get_async_db
from fastapi_app.main import app
from fastapi_app.shared_models import Base, ModificationLog, Role
from fastapi_app.shared_models.product import Product
from fastapi_app.shared_models.product_material import (
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
    ProductRole,
)

_TABLES = [
    Role.__table__,
    Product.__table__,
    ProductRole.__table__,
    ProductFabric.__table__,
    ProductAccessory.__table__,
    ProductMaterial.__table__,
    ModificationLog.__table__,
]

_URL = '/api/v1/purchase-center/product/{pid}/bom'


@pytest_asyncio.fixture
async def _real_session_engine():
    """真实异步内存 SQLite（StaticPool），含 btrim UDF。"""
    engine = create_async_engine(
        'sqlite+aiosqlite:///:memory:',
        poolclass=StaticPool,
        connect_args={'check_same_thread': False},
    )

    @event.listens_for(engine.sync_engine, 'connect')
    def _register_btrim(dbapi_connection, _record):  # pragma: no cover
        dbapi_connection.create_function(
            'btrim', 1, lambda v: v.strip() if isinstance(v, str) else v,
        )

    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=_TABLES))
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add(Product(id=1, name='端点回归-产品', price=1))
        await session.commit()
        yield session
    await engine.dispose()


async def _post(client: httpx.AsyncClient, pid: int, payload: dict):
    return await client.post(_URL.format(pid=pid), json=payload)


async def test_stale_role_id_returns_400_end_to_end(_real_session_engine):
    """payload 携带不属于该产品的角色 id → HTTP 400 且 detail 指名该 id。"""
    session = _real_session_engine

    async def _override_db():
        yield session

    # 仅替换数据库依赖为真实 session；权限用户依赖沿用 conftest 的 mock_current_user
    app.dependency_overrides[get_async_db] = _override_db

    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url='http://localhost',
        ) as client:
            client.headers.update(
                {'Authorization': 'Bearer endpoint-regression', 'Origin': 'http://localhost'},
            )

            # --- 1) 陈旧 id：产品 1 下并不存在 id=999 的角色关联行 ---
            stale = await _post(client, 1, {
                'roles': [{'id': 999, 'role_name': '陈旧角色'}],
                'fabrics': [], 'accessories': [],
            })
            assert stale.status_code == 400, (
                f'陈旧角色 id 应得 400，实得 {stale.status_code}: {stale.text[:200]}'
            )
            detail = stale.json().get('detail', '')
            assert '不属于该产品' in detail, f'detail 未指名归属错误: {detail!r}'
            assert '999' in detail, f'detail 未包含陈旧 id 999: {detail!r}'

            # 失败必须是回滚的：不得留下任何 ProductRole
            left = (await session.execute(select(ProductRole))).scalars().all()
            assert left == [], f'400 后不应残留 ProductRole，实得 {left}'

            # --- 2) 对照：合法 payload（新角色名）→ 200，证明 400 确由陈旧 id 触发 ---
            with patch(
                'fastapi_app.api.v1.endpoints.purchase_center.product_routes'
                '.cache_mgr.invalidate',
                new_callable=AsyncMock,
            ):
                ok = await _post(client, 1, {
                    'roles': [{'role_name': '端点回归角色'}],
                    'fabrics': [], 'accessories': [],
                })
            assert ok.status_code == 200, (
                f'合法 payload 应得 200，实得 {ok.status_code}: {ok.text[:200]}'
            )
            created = (await session.execute(select(ProductRole))).scalars().all()
            assert [r.role_name for r in created] == ['端点回归角色']
    finally:
        app.dependency_overrides.pop(get_async_db, None)
