"""批次管理的工厂隔离回归（上线前审计 2026-11-16 High 1）。

背景：订单侧写路径（update_batch_no / batch_assign / complete_batch）都有
`assert_*_factory_scoped` 闸门，备货侧 `update_stockin_batch_no` 漏了——厂绑定
非超管按自增 id 直改他厂备货的批次号（水平越权）。同一次审计还发现批次查询
列表的两个分支都只按客户白名单过滤、不按工厂过滤，于是「读看不见、改得动」
和「看得到别人的」两种口径并存。

本组用例锁死三条不变量：
  1) 备货写入口必须过产品工厂闸门，且闸门在改值之前（被拒不留半改状态）；
  2) 订单/备货两个读分支必须带同一套工厂条件（共用 `_factory_match`），
     且放行面与写侧一致（本厂 + NULL/空串历史行）；
  3) 超管/未绑定厂用户不受工厂收窄。
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from fastapi_app.services import order_batch_service
from fastapi_app.shared_models import Base, Order, OrderItem, Product, StockIn


def _user(*, factory, is_super):
    """厂绑定/超管用户桩：只喂 factory_scope_of 读的两个字段。"""
    user = MagicMock()
    user.id = 1
    user.username = '张三'
    user.factory = factory
    user.is_super = is_super
    return user


def _stockin(*, stockin_id=30, product_id=500, batch_no='OLD'):
    stockin = MagicMock()
    stockin.id = stockin_id
    stockin.product_id = product_id
    stockin.batch_no = batch_no
    return stockin


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


class TestUpdateStockinBatchNoFactoryGate:
    @pytest.mark.asyncio
    async def test_rejects_other_factory_stockin(self):
        """厂绑定非超管改他厂备货批次号 → 404，且批次号保持不变。

        拦的是「改得动他厂记录」：若有人把 `assert_product_factory_scoped`
        从 update_stockin_batch_no 里删掉，这里会变成默认可改、断言失败。
        """
        stockin = _stockin()
        db = AsyncMock()
        # 第 1 次 execute 取备货行（FOR UPDATE），第 2 次取产品工厂
        db.execute = AsyncMock(side_effect=[_scalar_result(stockin), _scalar_result('二分厂')])

        with pytest.raises(HTTPException) as exc:
            await order_batch_service.update_stockin_batch_no(
                db, stockin_id=30, batch_no='B9', user=_user(factory='一分厂', is_super=False),
            )

        assert exc.value.status_code == 404, '他厂备货对厂绑定用户必须是 404（不暴露记录存在）'
        assert stockin.batch_no == 'OLD', '闸门必须在改值之前：被拒时不得留下半改的批次号'

    @pytest.mark.asyncio
    async def test_allows_same_factory_stockin(self):
        """本厂备货照常放行（闸门不能把正常改批次号也拦掉）。"""
        stockin = _stockin()
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_scalar_result(stockin), _scalar_result('一分厂')])

        with patch.object(order_batch_service, '_safe_publish_event', new_callable=AsyncMock), \
             patch.object(order_batch_service, '_write_audit_log'):
            out = await order_batch_service.update_stockin_batch_no(
                db, stockin_id=30, batch_no='B9', user=_user(factory='一分厂', is_super=False),
            )

        assert out['updated_count'] == 1
        assert stockin.batch_no == 'B9'

    @pytest.mark.asyncio
    async def test_superuser_is_not_scoped(self):
        """超管不受工厂限制，且不额外查产品表（只 1 次 execute）。

        拦的是「把超管也一并 404」：闸门若漏掉 `not user.is_super` 判断，
        超管改他厂备货会被拒，这里会因抛 404 直接失败。
        """
        stockin = _stockin()
        db = AsyncMock()
        # 只允许 1 次 execute：超管绝不应该走到查产品工厂那一步
        db.execute = AsyncMock(side_effect=[_scalar_result(stockin)])

        with patch.object(order_batch_service, '_safe_publish_event', new_callable=AsyncMock), \
             patch.object(order_batch_service, '_write_audit_log'):
            out = await order_batch_service.update_stockin_batch_no(
                db, stockin_id=30, batch_no='B9', user=_user(factory='一分厂', is_super=True),
            )

        assert out['updated_count'] == 1
        assert stockin.batch_no == 'B9'
        assert db.execute.await_count == 1, '超管分支不应再查一次产品工厂'


@pytest_asyncio.fixture
async def sqlite_session():
    """真实异步内存 SQLite：只建 product / order / order_item / stock_in，绝不碰生产库。

    order_item 必须建：订单分支的工厂判定按 order_item → product 全量口径
    （与写侧 assert_orders_factory_scoped 同源），不建表就无从验证混厂场景。
    """
    engine = create_async_engine(
        'sqlite+aiosqlite:///:memory:',
        poolclass=StaticPool,
        connect_args={'check_same_thread': False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(
                c, tables=[Product.__table__, Order.__table__, OrderItem.__table__, StockIn.__table__],
            )
        )
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


def _seed_products(session):
    """四个产品覆盖读侧放行面的全部分支：本厂 / 他厂 / NULL / 空串。"""
    session.add_all([
        Product(id=1, name='本厂件', price=1, factory='一分厂'),
        Product(id=2, name='他厂件', price=1, factory='二分厂'),
        Product(id=3, name='未分配工厂的历史件', price=1, factory=None),
        Product(id=4, name='空串工厂的历史件', price=1, factory=''),
    ])


class TestStockinBranchFactoryFilter:
    @pytest.mark.asyncio
    async def test_branch_returns_only_own_factory_rows(self, sqlite_session):
        """真跑 SQL：他厂备货行不出现在结果里，本厂与未分配工厂的历史行保留。

        拦的是「列表返回他厂备货行」：把 factory_scope 分支删掉，四条都会返回，
        断言直接失败。
        """
        session = sqlite_session
        _seed_products(session)
        session.add_all([
            StockIn(id=11, stockin_no='SI-11', customer='贝乐', product_id=1, quantity=1),
            StockIn(id=12, stockin_no='SI-12', customer='贝乐', product_id=2, quantity=1),
            StockIn(id=13, stockin_no='SI-13', customer='贝乐', product_id=3, quantity=1),
            StockIn(id=14, stockin_no='SI-14', customer='贝乐', product_id=4, quantity=1),
        ])
        await session.flush()

        branch = order_batch_service._build_batch_stockin_branch(
            whitelist=None, batch_no=None, customer=None, keyword=None, factory_scope='一分厂',
        )
        rows = (await session.execute(branch)).all()
        ids = sorted(row.record_id for row in rows)

        assert ids == [11, 13, 14], (
            f'厂绑定用户只应看到本厂(11)、未分配工厂(13)、空串工厂(14)的备货行，实得 {ids}'
        )

    def test_branch_filters_out_other_factory_rows(self):
        """备货读分支带工厂条件，放行面与写侧闸门一致（本厂 + NULL + 空串）。

        拦的是「列表返回他厂备货行」：删掉 factory_scope 分支后 SQL 里不再有
        product.factory 条件，这两条断言会失败。
        """
        branch = order_batch_service._build_batch_stockin_branch(
            whitelist=None, batch_no=None, customer=None, keyword=None, factory_scope='一分厂',
        )
        compiled = branch.compile()
        sql = str(compiled)

        assert 'JOIN product' in sql
        assert 'product.factory IS NULL' in sql
        assert 'product.factory = :factory_2' in sql
        # 本厂值必须进绑定参数，空串也要在（未分配工厂的历史行读放行）
        assert set(compiled.params.values()) >= {'一分厂', ''}

    def test_branch_joins_product_once_with_keyword(self):
        """keyword 与工厂过滤同时生效时只 JOIN 一次 product（重复 JOIN 会报歧义）。"""
        branch = order_batch_service._build_batch_stockin_branch(
            whitelist=None, batch_no=None, customer=None, keyword='企鹅', factory_scope='一分厂',
        )
        sql = str(branch.compile())

        assert sql.count('JOIN product') == 1
        assert 'product.factory IS NULL' in sql
        assert 'product.name' in sql

    def test_branch_has_no_factory_condition_when_unscoped(self):
        """超管/未绑定厂（factory_scope 空串）不 JOIN product，行为与改动前一致。"""
        branch = order_batch_service._build_batch_stockin_branch(
            whitelist=None, batch_no=None, customer=None, keyword=None, factory_scope='',
        )
        sql = str(branch.compile())

        assert 'product' not in sql.lower()


class TestOrderBranchFactoryFilter:
    @pytest.mark.asyncio
    async def test_branch_returns_only_own_factory_rows(self, sqlite_session):
        """真跑 SQL：订单分支与备货分支同口径——他厂订单不出现，历史空厂订单保留。

        拦的是「订单侧口径没收窄」（A-5 第二半）：订单分支若漏掉 factory_scope，
        四条订单都会返回，断言失败。
        """
        session = sqlite_session
        _seed_products(session)
        session.add_all([
            Order(id=21, order_no='PO-21', customer='贝乐', quantity=1, product_id=1),
            Order(id=22, order_no='PO-22', customer='贝乐', quantity=1, product_id=2),
            Order(id=23, order_no='PO-23', customer='贝乐', quantity=1, product_id=3),
            Order(id=24, order_no='PO-24', customer='贝乐', quantity=1, product_id=4),
            # 混厂订单：首个 SKU 是本厂（兼容字段 product_id=1），另含一条他厂 SKU
            Order(id=25, order_no='PO-25', customer='贝乐', quantity=2, product_id=1),
        ])
        session.add_all([
            OrderItem(order_id=21, product_id=1, quantity=1),
            OrderItem(order_id=22, product_id=2, quantity=1),
            OrderItem(order_id=23, product_id=3, quantity=1),
            OrderItem(order_id=24, product_id=4, quantity=1),
            OrderItem(order_id=25, product_id=1, quantity=1),
            OrderItem(order_id=25, product_id=2, quantity=1),
        ])
        await session.flush()

        branch = order_batch_service._build_batch_order_branch(
            whitelist=None, batch_no=None, status=None, customer=None, keyword=None,
            factory_scope='一分厂',
        )
        rows = (await session.execute(branch)).all()
        ids = sorted(row.record_id for row in rows)

        # 判定按 order_item → product **全量**（与写侧 assert_orders_factory_scoped 同源）：
        # 21 本厂 / 23 未分配 / 24 空串放行；22 全他厂排除；
        # 25 混厂也必须排除 —— 否则「列表看得见、改批次号 404」（评审 F4）。
        assert ids == [21, 23, 24], (
            f'厂绑定用户只应看到本厂(21)、未分配工厂(23)、空串工厂(24)的订单行，实得 {ids}'
        )
        assert 25 not in ids, '混厂订单（含他厂 SKU）必须整体不可见，与写侧 404 同口径'

    @pytest.mark.asyncio
    async def test_superuser_sees_all_factory_rows(self, sqlite_session):
        """超管/未绑定厂（factory_scope 空串）不收窄：四条订单都返回。

        拦的是「把超管也一并收窄」：漏掉 `factory_scope_of` 的超管空串分支时，
        超管会突然看不见别厂订单。
        """
        session = sqlite_session
        _seed_products(session)
        session.add_all([
            Order(id=21, order_no='PO-21', customer='贝乐', quantity=1, product_id=1),
            Order(id=22, order_no='PO-22', customer='贝乐', quantity=1, product_id=2),
            Order(id=23, order_no='PO-23', customer='贝乐', quantity=1, product_id=3),
            Order(id=24, order_no='PO-24', customer='贝乐', quantity=1, product_id=4),
        ])
        await session.flush()

        branch = order_batch_service._build_batch_order_branch(
            whitelist=None, batch_no=None, status=None, customer=None, keyword=None,
            factory_scope='',
        )
        rows = (await session.execute(branch)).all()
        ids = sorted(row.record_id for row in rows)

        assert ids == [21, 22, 23, 24], f'超管不应被工厂收窄，实得 {ids}'

    def test_branch_has_no_factory_condition_when_unscoped(self):
        """未收窄时不 JOIN product：编译出的 SQL 与改动前逐字等价。"""
        branch = order_batch_service._build_batch_order_branch(
            whitelist=None, batch_no=None, status=None, customer=None, keyword=None,
            factory_scope='',
        )
        sql = str(branch.compile())

        assert 'product' not in sql.lower()
        assert 'is_deleted' in sql

    def test_branch_uses_correlated_exists_for_factory(self):
        """工厂条件走 order_item 的关联 EXISTS，keyword 用 LEFT JOIN product。

        评审 F4 之后的口径：工厂判定不能再靠「主查询 JOIN product」——那只能看到
        Order.product_id（首个 SKU 的兼容字段），混厂订单会「列表看得见、改批次号 404」。
        同时 keyword 仍需要 product.name，故主查询保留**一次 LEFT OUTER JOIN**
        （INNER 会让 product_id 为空的历史订单整行消失）。
        """
        branch = order_batch_service._build_batch_order_branch(
            whitelist=None, batch_no=None, status=None, customer=None, keyword='PO-1',
            factory_scope='一分厂',
        )
        sql = str(branch.compile()).upper()

        assert 'LEFT OUTER JOIN PRODUCT' in sql
        assert 'EXISTS' in sql, '工厂条件应走关联 EXISTS（order_item → product 全量判定）'
        assert 'ORDER_ITEM' in sql
        assert 'PRODUCT.NAME' in sql
