"""ProductRole.global_role_id 约束回归测试（真实 ORM + 真实 create_all）

背景
----
``pg_standalone_045_global_role.py`` 迁移给 ``product_role.global_role_id`` 加了：

1. ``NOT NULL``（回填后 SET NOT NULL）；
2. 外键 ``ON DELETE RESTRICT``（外键指向全局角色字典 ``role.id``）；
3. 唯一约束 ``uq_product_role_product_global(product_id, global_role_id)``。

但若 ORM（``shared_models/product_material.py``）把它声明为可空
（``Mapped[int | None]``），测试库走 ``Base.metadata.create_all`` 建出的
``global_role_id`` 就是**可空**的，于是「违约代码」在 CI 里静默通过、到生产
才炸。本用例在真实 SQLAlchemy session + 真实 ``create_all`` 上断言四条约束
真实生效，从而证伪上述「ORM 与迁移不一致」回归。

fail-before / pass-after
------------------------
``test_global_role_id_not_null`` 是 fail-before 用例：ORM 列可空时插入成功
（断言 IntegrityError 失败）；ORM 列改为 NOT NULL 后才真正抛 IntegrityError。
其余三条分别锁定「悬空外键 / 同产品重复全局角色 / 被引用角色禁止删除」。

仅使用内存 SQLite，不触碰生产数据。
"""
import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from fastapi_app.shared_models import Base, Role
from fastapi_app.shared_models.product import Product
from fastapi_app.shared_models.product_material import ProductRole

# 仅建本用例涉及的表，避免拖入无关依赖链
_TABLES = [
    Role.__table__,
    Product.__table__,
    ProductRole.__table__,
]


@pytest_asyncio.fixture
async def fk_session():
    """真实异步 session（内存 SQLite，StaticPool 保证同一连接同一库）。

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
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


async def _seed_product(db) -> None:
    """建一个基础产品（ProductRole.product_id 外键目标）。"""
    db.add(Product(id=1, name='FK约束-产品', price=1))
    await db.flush()


async def test_global_role_id_not_null(fk_session):
    """fail-before：不传 global_role_id 必须被 NOT NULL 拒绝。

    ORM 若声明为 ``Mapped[int | None]``（可空）→ create_all 建出可空列 →
    本断言失败；改回 ``Mapped[int]`` + ``nullable=False`` 后才通过。
    """
    db = fk_session
    await _seed_product(db)

    db.add(ProductRole(product_id=1, role_name='无全局角色'))
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


async def test_unknown_global_role_id_violates_fk(fk_session):
    """global_role_id 指向不存在的全局角色 → 外键违约（FK RESTRICT）。"""
    db = fk_session
    await _seed_product(db)

    db.add(ProductRole(product_id=1, global_role_id=9999, role_name='悬空角色'))
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


async def test_duplicate_product_global_role_rejected(fk_session):
    """同一产品重复关联同一全局角色 → uq_product_role_product_global 违约。"""
    db = fk_session
    await _seed_product(db)

    role = Role(name='共享角色')
    db.add(role)
    await db.flush()

    db.add(ProductRole(product_id=1, global_role_id=role.id, role_name='共享角色'))
    await db.flush()

    db.add(ProductRole(product_id=1, global_role_id=role.id, role_name='共享角色'))
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


async def test_delete_referenced_role_restricted(fk_session):
    """删除被产品引用的全局角色 → ON DELETE RESTRICT 违约（禁止删除）。"""
    db = fk_session
    await _seed_product(db)

    role = Role(name='被引用角色')
    db.add(role)
    await db.flush()

    db.add(ProductRole(product_id=1, global_role_id=role.id, role_name='被引用角色'))
    await db.flush()

    await db.delete(role)
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()
