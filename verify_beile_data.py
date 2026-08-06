"""验证湖北工厂备货订单数据."""
import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 sys.path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import joinedload

async def main():
    url = "postgresql+asyncpg://erp_app:110110@localhost:5432/erp_system"
    engine = create_async_engine(url, echo=False)
    async with engine.connect() as conn:
        # 1. 查询湖北工厂的备货记录
        result = await conn.execute(text("""
            SELECT si.id, si.stockin_no, si.customer, si.quantity,
                   si.stockin_date, p.name as product_name, p.factory, p.barcode
            FROM stock_in si
            JOIN product p ON si.product_id = p.id
            WHERE p.factory = '湖北'
            ORDER BY si.stockin_date DESC
            LIMIT 10
        """))
        rows = result.fetchall()
        print(f"\n=== 湖北工厂备货记录 (stock_in) ===")
        print(f"共 {len(rows)} 条:")
        for r in rows:
            print(f"  ID={r[0]} NO={r[1]} 客户={r[2]} 数量={r[3]} 日期={r[4]} 产品={r[5]} 工厂={r[6]} 条码={r[7]}")

        # 2. 查询湖北工厂的订单记录
        result = await conn.execute(text("""
            SELECT DISTINCT o.id, o.order_no, o.customer, o.order_date, o.status
            FROM "order" o
            JOIN order_item oi ON o.id = oi.order_id
            JOIN product p ON oi.product_id = p.id
            WHERE p.factory = '湖北' AND o.is_deleted = false
            ORDER BY o.order_date DESC
            LIMIT 10
        """))
        rows = result.fetchall()
        print(f"\n=== 湖北工厂订单 (order) ===")
        print(f"共 {len(rows)} 条:")
        for r in rows:
            print(f"  ID={r[0]} NO={r[1]} 客户={r[2]} 日期={r[3]} 状态={r[4]}")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
