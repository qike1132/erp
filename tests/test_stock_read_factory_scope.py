"""P0-2 回归：库存读查询的工厂隔离。

厂绑定用户（User.factory 非空且非超管）只能看到本厂产品（含未分配工厂的
历史产品）的备货/出库/库存行与客户快捷栏。本文件直接调用 service 层。
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete

from fastapi_app.services import stock_service
from fastapi_app.services.stock_inventory_service import get_stockout_records
from fastapi_app.shared_models import Product, StockIn, StockOut


def _unwrap(fn):
    """绕过 cache_result，避免测试间缓存串味。"""
    return getattr(fn, '__wrapped__', fn)


class TestStockReadFactoryScope:
    async def test_read_queries_filtered_by_factory(self, async_db_session):
        db = async_db_session
        tag = uuid.uuid4().hex[:8]
        cust_c = f'C-{tag}'      # 东莞 + 未分配
        cust_h = f'H-{tag}'      # 仅湖北
        p_dg = Product(name=f'DG-{tag}', barcode=f'DG{tag}', factory='东莞')
        p_hb = Product(name=f'HB-{tag}', barcode=f'HB{tag}', factory='湖北')
        # 未分配工厂的历史产品：与写侧 factory_scope 口径一致，读侧对厂用户放行
        p_na = Product(name=f'NA-{tag}', barcode=f'NA{tag}', factory=None)
        db.add_all([p_dg, p_hb, p_na])
        await db.flush()
        si_dg = StockIn(stockin_no=f'SI{tag}1', customer=cust_c, product_id=p_dg.id, quantity=2)
        si_hb = StockIn(stockin_no=f'SI{tag}2', customer=cust_h, product_id=p_hb.id, quantity=3)
        si_na = StockIn(stockin_no=f'SI{tag}3', customer=cust_c, product_id=p_na.id, quantity=4)
        db.add_all([si_dg, si_hb, si_na])
        so_dg = StockOut(stockout_no=f'SO{tag}1', customer=cust_c, product_id=p_dg.id, quantity=1,
                         stockout_date=datetime.now(UTC))
        so_hb = StockOut(stockout_no=f'SO{tag}2', customer=cust_h, product_id=p_hb.id, quantity=1,
                         stockout_date=datetime.now(UTC))
        so_na = StockOut(stockout_no=f'SO{tag}3', customer=cust_c, product_id=p_na.id, quantity=1,
                         stockout_date=datetime.now(UTC))
        db.add_all([so_dg, so_hb, so_na])
        await db.commit()

        try:
            # 备货列表：本厂 + 未分配，不含湖北
            scoped = await _unwrap(stock_service.get_stockins)(db, factory='东莞')
            names = {item['product']['name'] for item in scoped['items'] if tag in item['product']['name']}
            assert names == {f'DG-{tag}', f'NA-{tag}'}

            unscoped = await _unwrap(stock_service.get_stockins)(db, factory=None)
            names_all = {item['product']['name'] for item in unscoped['items'] if tag in item['product']['name']}
            assert names_all == {f'DG-{tag}', f'HB-{tag}', f'NA-{tag}'}

            # 出库列表
            so_scoped = await _unwrap(stock_service.get_stockouts)(db, factory='东莞')
            so_names = {item['product']['name'] for item in so_scoped['items'] if tag in item['product']['name']}
            assert so_names == {f'DG-{tag}', f'NA-{tag}'}

            # 按单号还原明细：他厂单号在厂用户下必须为空
            assert await get_stockout_records(
                db, kind='stockout', nos=so_hb.stockout_no, factory='东莞') == []
            assert len(await get_stockout_records(
                db, kind='stockout', nos=so_hb.stockout_no, factory=None)) == 1

            # 库存 CTE：行与客户快捷栏都按工厂收窄
            inventory = await stock_service.get_inventory_paginated(
                db, search_product=tag, factory='东莞',
            )
            assert {row['product_name'] for row in inventory['inventory_data']} == {
                f'DG-{tag}', f'NA-{tag}',
            }
            assert cust_h not in inventory['all_customers']

            inventory_all = await stock_service.get_inventory_paginated(
                db, search_product=tag, factory='',
            )
            assert {row['product_name'] for row in inventory_all['inventory_data']} == {
                f'DG-{tag}', f'HB-{tag}', f'NA-{tag}',
            }
            assert cust_h in inventory_all['all_customers']
        finally:
            await db.execute(delete(StockOut).where(
                StockOut.id.in_([so_dg.id, so_hb.id, so_na.id])))
            await db.execute(delete(StockIn).where(
                StockIn.id.in_([si_dg.id, si_hb.id, si_na.id])))
            await db.execute(delete(Product).where(
                Product.id.in_([p_dg.id, p_hb.id, p_na.id])))
            await db.commit()
