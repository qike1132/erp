"""ProductRole 私有化阶段 1 约束回归（真实 ORM + 真实 create_all）

背景
----
迁移 088（阶段 1，非破坏性）把角色从「跨产品共享」退回「产品私有」：

1. ``product_role.global_role_id`` 由 ``NOT NULL`` 放宽为**可空**（新代码不再写它）；
2. 删除唯一约束 ``uq_product_role_product_global``；
3. 新建**产品内**角色名唯一索引
   ``uq_product_role_product_name_lower (product_id, lower(role_name))``。

``role`` 表、外键 ``fk_product_role_global_role``（``ON DELETE RESTRICT``）与
``uq_role_name_lower`` **本阶段保留**（迁移 089 才删 role 层）。

ORM（``shared_models/product_material.py``）必须与上述 DDL 同步，否则
``Base.metadata.create_all`` 建出的测试库与生产不一致 → 违约代码在 CI 静默通过。
本用例在真实 SQLAlchemy session + 真实 ``create_all`` 上断言。

仅使用内存 SQLite，不触碰生产数据。
"""
import pytest
import pytest_asyncio
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from fastapi_app.shared_models import Base, Role
from fastapi_app.shared_models.product import Product
from fastapi_app.shared_models.product_material import ProductRole

_TABLES = [
    Role.__table__,
    Product.__table__,
    ProductRole.__table__,
]


@pytest_asyncio.fixture
async def fk_engine():
    """真实内存 SQLite 引擎（StaticPool 保证同一连接同一库）。

    显式开启 ``PRAGMA foreign_keys=ON``，否则 SQLite 默认**不强制**外键，
    悬空 ``global_role_id`` / ``ON DELETE RESTRICT`` 两条断言会假绿。
    """
    engine = create_async_engine(
        'sqlite+aiosqlite:///:memory:',
        poolclass=StaticPool,
        connect_args={'check_same_thread': False},
    )

    @event.listens_for(engine.sync_engine, 'connect')
    def _enable_foreign_keys(dbapi_connection, _record):  # pragma: no cover - 连接级回调
        cursor = dbapi_connection.cursor()
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=_TABLES))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def fk_session(fk_engine):
    """真实异步 session（复用 fk_engine 建好的同一内存库）。"""
    session_factory = async_sessionmaker(fk_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


async def _seed_products(db) -> None:
    db.add(Product(id=1, name='私有角色-产品1', price=1))
    db.add(Product(id=2, name='私有角色-产品2', price=1))
    await db.flush()


async def test_global_role_id_is_nullable_after_p1(fk_session):
    """阶段 1 起 ``global_role_id`` 可空：不传它也能建角色行（新代码不再写该列）。"""
    db = fk_session
    await _seed_products(db)

    db.add(ProductRole(product_id=1, role_name='无全局角色'))
    await db.flush()  # 不抛错 = 列已可空


async def test_unknown_global_role_id_violates_fk(fk_session):
    """本阶段外键仍在：global_role_id 指向不存在的角色 → 外键违约。"""
    db = fk_session
    await _seed_products(db)

    db.add(ProductRole(product_id=1, global_role_id=9999, role_name='悬空角色'))
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


async def test_delete_referenced_role_restricted(fk_session):
    """本阶段 FK ``ON DELETE RESTRICT`` 仍在：删除被引用的 role 行被拒。"""
    db = fk_session
    await _seed_products(db)

    role = Role(name='被引用角色')
    db.add(role)
    await db.flush()

    db.add(ProductRole(product_id=1, global_role_id=role.id, role_name='被引用角色'))
    await db.flush()

    await db.delete(role)
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


async def test_same_product_duplicate_role_name_rejected(fk_session):
    """同一产品内角色名大小写不敏感唯一 → 第二次插入违约（新索引生效）。

    用 ASCII ``X``/``x`` 是因为 SQLite 内建 ``lower()`` 仅对 ASCII 生效，
    故 ``lower('角色X') == lower('角色x')``，同键冲突确定可复现。
    """
    db = fk_session
    await _seed_products(db)

    db.add(ProductRole(product_id=1, role_name='角色X'))
    await db.flush()

    db.add(ProductRole(product_id=1, role_name='角色x'))
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


async def test_same_name_across_products_allowed(fk_session):
    """跨产品同名允许（角色产品私有，互不影响）——这是本次改造的核心语义。"""
    db = fk_session
    await _seed_products(db)

    db.add(ProductRole(product_id=1, role_name='共用角色'))
    db.add(ProductRole(product_id=2, role_name='共用角色'))
    await db.flush()  # 不抛错 = 跨产品同名不再冲突


async def test_product_role_name_unique_index_exists(fk_engine):
    """结构断言：测试库存在产品内角色名唯一索引（表达式索引走 sqlite_master）。"""
    async with fk_engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='product_role'"
        ))).all()

    index_sql = {row[0]: (row[1] or '') for row in rows}
    assert 'uq_product_role_product_name_lower' in index_sql, (
        f'product_role 缺少 uq_product_role_product_name_lower，实得 {sorted(index_sql)}'
    )
    ddl = index_sql['uq_product_role_product_name_lower']
    assert 'UNIQUE' in ddl.upper(), f'索引非唯一：{ddl}'
    assert 'lower(role_name)' in ddl, f'索引表达式非 lower(role_name)：{ddl}'


async def test_old_global_unique_constraint_absent(fk_engine):
    """结构断言：阶段 1 已删除 uq_product_role_product_global（ORM 也不应再声明）。"""
    async with fk_engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='product_role'"
        ))).all()
    index_sql = {row[0]: (row[1] or '') for row in rows}
    assert 'uq_product_role_product_global' not in index_sql, (
        f'旧唯一约束仍存在，应已随 088 删除：{sorted(index_sql)}'
    )


async def test_role_name_lower_unique_index_exists(fk_engine):
    """结构断言：``role`` 表本阶段仍保留 uq_role_name_lower（089 才随表删除）。"""
    async with fk_engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='role'"
        ))).all()

    index_sql = {row[0]: (row[1] or '') for row in rows}
    assert 'uq_role_name_lower' in index_sql, f'role 表缺少 uq_role_name_lower，实得 {sorted(index_sql)}'
