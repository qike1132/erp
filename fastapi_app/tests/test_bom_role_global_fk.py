"""ProductRole.global_role_id 约束 + Role.name 函数唯一索引 回归测试（真实 ORM + 真实 create_all）

背景
----
``pg_standalone_045_global_role.py`` 迁移给 ``role`` / ``product_role`` 加了：

1. ``role`` 表函数唯一索引 ``uq_role_name_lower ON role (lower(name))``（大小写不敏感唯一）；
2. ``product_role.global_role_id`` 的 ``NOT NULL``（回填后 SET NOT NULL）；
3. 外键 ``ON DELETE RESTRICT``（外键指向全局角色字典 ``role.id``）；
4. 唯一约束 ``uq_product_role_product_global(product_id, global_role_id)``。

但若 ORM（``shared_models/product_material.py``）未同步声明这些约束，测试库走
``Base.metadata.create_all`` 建出的结构就与生产 DDL 不一致，于是「违约代码」在 CI 里
静默通过、到生产才炸。本用例在真实 SQLAlchemy session + 真实 ``create_all`` 上断言这些
约束真实生效，从而证伪「ORM 与迁移不一致」回归。

fail-before / pass-after
------------------------
- ``test_global_role_id_not_null``：ORM 列可空时插入成功（断言失败）；改为 NOT NULL 后通过。
- ``test_role_name_case_insensitive_unique``：ORM 未声明 ``uq_role_name_lower`` 时，仅大小写
  不同的第二次插入成功（断言失败）；补上该函数唯一索引后真正抛 IntegrityError。
- ``test_role_name_lower_unique_index_exists``：结构断言，直接证明测试库 DDL 里已有该索引。
其余两条分别锁定「悬空外键 / 同产品重复全局角色 / 被引用角色禁止删除」。

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

# 仅建本用例涉及的表，避免拖入无关依赖链
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


async def test_role_name_lower_unique_index_exists(fk_engine):
    """结构断言：create_all 建出的测试库上存在 uq_role_name_lower 唯一索引。

    注意：SQLite 的 ``inspect(...).get_indexes('role')`` 会**跳过表达式索引**
    （``Skipped unsupported reflection of expression-based index uq_role_name_lower``），
    故这里直接查 ``sqlite_master``——能看到真实索引 DDL 与 unique 标记。
    """
    async with fk_engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='role'"
        ))).all()

    index_sql = {row[0]: (row[1] or '') for row in rows}
    assert 'uq_role_name_lower' in index_sql, f'role 表缺少 uq_role_name_lower，实得 {sorted(index_sql)}'
    ddl = index_sql['uq_role_name_lower']
    assert 'UNIQUE' in ddl.upper(), f'索引非唯一：{ddl}'
    assert 'lower(name)' in ddl, f'索引表达式非 lower(name)：{ddl}'


async def test_role_name_case_insensitive_unique(fk_session):
    """行为断言（fail-before / pass-after）：仅大小写不同的角色名必须被拒绝。

    ORM 未声明该函数唯一索引（修复前）→ 测试库无该约束 → 第二次插入成功，
    本断言失败；ORM 补上 ``uq_role_name_lower(text('lower(name)'))``（修复后）
    → 第二次插入抛 IntegrityError。

    用 ASCII 字母 ``X``/``x`` 是因为 SQLite 内建 ``lower()`` 仅对 ASCII 生效，
    故 ``lower('测试角色X') == lower('测试角色x')``，同键冲突确定可复现。
    """
    db = fk_session
    db.add(Role(name='测试角色X'))
    await db.flush()

    db.add(Role(name='测试角色x'))
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()
