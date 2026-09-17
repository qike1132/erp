"""BOM 复制·默认分支「复制源产品角色」的真实 ORM 守卫测试（F3）。

覆盖缺口
--------
``bom_service.copy_bom`` 在 **role_id 与 role_name 均未传** 时走「原有逻辑」分支，
其中包含一段「复制源产品角色及其独立物料」的循环
（``bom_service.py`` 中 ``for old_role in source_product.roles:`` →
``global_role_id=gid,`` 所在的 F3 修复点）。该循环此前**无真实会话覆盖**：

- ``test_bom_copy_role_orm.py`` 只给**目标产品**建了 ``ProductRole``，
  **源产品** ``roles`` 为空 ⇒ F3 循环体从不执行，删掉 ``global_role_id=gid`` 也不会失败；
- ``test_bom_role.py::TestCopyBom`` 用 ``MagicMock``/``AsyncMock`` 假会话，
  假会话不会抛 ``IntegrityError``，**无法观察 NOT NULL 违约**。

本用例用**真实内存 SQLite + ``Base.metadata.create_all``** 驱动默认分支。
建表 DDL 取自 ORM metadata，而 ORM 已把 ``product_role.global_role_id`` 收紧为
``Mapped[int]``/``nullable=False``（与迁移 ``pg_standalone_045_global_role`` 的
NOT NULL + FK 对齐）——因此**实现若漏写 ``global_role_id=gid``，flush 时会抛
NOT NULL 的 IntegrityError**，用例即失败。这正是「F3 真守卫」的判据。

⚠️ 该守卫的有效性**依赖 ORM 列声明为 nullable=False**：若回退为可空，
``create_all`` 会建出可空列，变异将不再被发现（ORM↔迁移不一致的历史根因）。
仅使用内存库，不触碰生产数据。
"""
from decimal import Decimal

import pytest_asyncio
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from fastapi_app.services import bom_service
from fastapi_app.shared_models import Base, Role
from fastapi_app.shared_models.product import Product
from fastapi_app.shared_models.product_material import (
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
    ProductRole,
)

# 仅建 copy_bom 默认分支会访问到的表。
_TABLES = [
    Role.__table__,
    Product.__table__,
    ProductRole.__table__,
    ProductFabric.__table__,
    ProductAccessory.__table__,
    ProductMaterial.__table__,
]


@pytest_asyncio.fixture
async def real_db_session():
    """真实异步 SQLAlchemy session（内存 SQLite，StaticPool 保证同一连接同一库）。"""
    engine = create_async_engine(
        'sqlite+aiosqlite:///:memory:',
        poolclass=StaticPool,
        connect_args={'check_same_thread': False},
    )

    @event.listens_for(engine.sync_engine, 'connect')
    def _register_btrim(dbapi_connection, _record):  # pragma: no cover - 连接级回调
        # SQLite 无 btrim（PostgreSQL 内置）。copy_bom → ensure_global_role 会用
        # lower(btrim(name)) 查全局角色字典，此处补一个等价的空格 trim 实现。
        dbapi_connection.create_function(
            'btrim', 1, lambda value: value.strip() if isinstance(value, str) else value,
        )

    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=_TABLES))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


async def _seed_source_role(db) -> tuple[Role, ProductRole]:
    """源产品（id=1）挂一个全局角色 + 角色级面料/辅料；目标产品（id=2）留空。

    Returns:
        (源全局角色 role, 源产品关联行 product_role)。
    """
    db.add_all([
        Product(id=1, name='F3守卫-源产品', price=1),
        Product(id=2, name='F3守卫-目标产品', price=1),
    ])
    await db.flush()

    src_global = Role(name='源角色A')
    db.add(src_global)
    await db.flush()

    src_assoc = ProductRole(
        product_id=1, global_role_id=src_global.id, role_name='源角色A',
    )
    db.add(src_assoc)
    await db.flush()

    db.add_all([
        ProductFabric(
            product_id=1, role_id=src_assoc.id, fabric_name='源角色A面料',
            quantity=Decimal('2'), unit='码',
        ),
        ProductAccessory(
            product_id=1, role_id=src_assoc.id, accessory_name='源角色A辅料',
            quantity=Decimal('1'), unit='个',
        ),
    ])
    await db.commit()
    return src_global, src_assoc


async def _rows_for(db, model, product_id: int) -> list:
    result = await db.execute(select(model).where(model.product_id == product_id))
    return list(result.scalars().all())


async def test_copy_bom_default_branch_reuses_source_global_role(real_db_session):
    """默认分支（不传 role_id / role_name）复制源产品角色：新关联行复用源的全局角色 id。

    核心断言：目标新增 ``ProductRole.global_role_id`` **等于源关联行的 global_role_id**
    （同一 ``role`` 行跨产品复用），且复制出的角色级面料/辅料 ``role_id`` 指向新关联行。
    """
    db = real_db_session
    src_global, src_assoc = await _seed_source_role(db)

    result = await bom_service.copy_bom(
        db, 2, {'source_product_id': 1, 'overwrite': False}, 'tester',
    )
    await db.flush()

    # a) 目标产品新增 1 条 ProductRole，且其 global_role_id 复用源的 gid
    target_roles = await _rows_for(db, ProductRole, 2)
    assert len(target_roles) == 1, f'应复制出 1 条目标角色，实得 {len(target_roles)}'
    new_role = target_roles[0]
    assert new_role.global_role_id == src_global.id, (
        f'global_role_id 必须复用源全局角色 {src_global.id}，'
        f'实得 {new_role.global_role_id!r}（漏写即触发 NOT NULL 违约）'
    )
    assert new_role.role_name == '源角色A'
    assert new_role.id != src_assoc.id, '目标关联行必须是新行，不得复用源关联行 id'

    # b) 只有一行全局角色（复用，不重复建）
    global_count = await db.scalar(select(func.count()).select_from(Role))
    assert global_count == 1

    # c) 复制出的角色级面料/辅料 role_id 指向新关联行
    tgt_fabrics = await _rows_for(db, ProductFabric, 2)
    tgt_accessories = await _rows_for(db, ProductAccessory, 2)
    assert len(tgt_fabrics) == 1 and {f.role_id for f in tgt_fabrics} == {new_role.id}
    assert len(tgt_accessories) == 1 and {a.role_id for a in tgt_accessories} == {new_role.id}

    # d) 计数 = 1 角色 + 1 面料 + 1 辅料（源产品无产品级默认物料）
    assert result['copied_count'] == 3


async def test_copy_bom_default_branch_reuses_existing_target_role(
    real_db_session,
):
    """目标已关联同一全局角色 → 复用该关联行（不新建、不撞唯一约束），物料挂到既有行。"""
    db = real_db_session
    # 预置全局角色 + 目标关联行，再把源的 global_role_id 指向同一条
    preexisting = Role(name='源角色A')
    db.add_all([
        Product(id=1, name='F3去重-源产品', price=1),
        Product(id=2, name='F3去重-目标产品', price=1),
    ])
    await db.flush()
    db.add(preexisting)
    await db.flush()

    src_assoc = ProductRole(
        product_id=1, global_role_id=preexisting.id, role_name='源角色A',
    )
    tgt_assoc = ProductRole(
        product_id=2, global_role_id=preexisting.id, role_name='源角色A',
    )
    db.add_all([src_assoc, tgt_assoc])
    await db.flush()
    db.add(ProductFabric(
        product_id=1, role_id=src_assoc.id, fabric_name='源角色A面料',
        quantity=Decimal('2'), unit='码',
    ))
    await db.commit()

    await bom_service.copy_bom(db, 2, {'source_product_id': 1, 'overwrite': False}, 'tester')
    await db.flush()

    target_roles = await _rows_for(db, ProductRole, 2)
    assert len(target_roles) == 1, '目标已关联同一全局角色 → 必须复用，不得新建'
    assert target_roles[0].id == tgt_assoc.id

    tgt_fabrics = await _rows_for(db, ProductFabric, 2)
    assert len(tgt_fabrics) == 1 and tgt_fabrics[0].role_id == tgt_assoc.id
