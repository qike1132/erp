#!/usr/bin/env python3
"""
出库操作模拟脚本 - 用于验证实时同步功能

这个脚本可以：
1. 模拟 ERP 系统执行出库操作
2. 触发 WebSocket 实时通知
3. 验证 dashboard 缓存失效机制
4. 观察前端实时同步效果

使用方法：
    python scripts/simulate_stockout.py --help
"""
import argparse
import asyncio
import datetime
import logging

# 添加项目根目录到 Python 路径
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fastapi_app.core.cache import invalidate_cache
from fastapi_app.core.database import _AsyncSessionLocal
from fastapi_app.services import stock_service
from fastapi_app.services.notification_service import StockEvent, publish_stock_event
from fastapi_app.shared_models import Product

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def get_available_product(db) -> Product | None:
    """获取一个可用的产品（有库存的）"""
    result = await db.execute(Product.__table__.select().where(Product.current_stock > 0).limit(1))
    product = result.first()
    return product


async def simulate_stockout(
    product_id: int | None = None,
    quantity: int = 10,
    customer: str = "测试客户",
    note: str = "实时同步测试出库"
):
    """
    模拟出库操作

    Args:
        product_id: 产品 ID（可选，不指定则自动选择）
        quantity: 出库数量
        customer: 客户名称
        note: 备注
    """
    logger.info("=" * 60)
    logger.info("开始模拟出库操作...")
    logger.info("=" * 60)

    async with _AsyncSessionLocal() as db:
        try:
            # Step 1: 获取产品信息
            if product_id is None:
                # 自动选择一个有库存的产品
                product = await get_available_product(db)
                if not product:
                    logger.error("没有找到有库存的产品，请先创建或入库！")
                    return
                product_id = product.id
                logger.info(f"自动选择产品: ID={product.id}, 名称={product.name}, 当前库存={product.current_stock}")
            else:
                # 使用指定的产品
                result = await db.execute(Product.__table__.select().where(Product.id == product_id))
                product = result.first()
                if not product:
                    logger.error(f"找不到产品 ID={product_id}")
                    return
                logger.info(f"使用指定产品: ID={product.id}, 名称={product.name}, 当前库存={product.current_stock}")

            # Step 2: 生成日期（今天）
            stockout_date_str = datetime.datetime.now().strftime('%Y-%m-%d')

            # Step 3: 显示出库信息预览
            logger.info("-" * 60)
            logger.info("出库信息预览:")
            logger.info(f"  产品: {product.name} (ID: {product_id})")
            logger.info(f"  客户: {customer}")
            logger.info(f"  数量: {quantity}")
            logger.info(f"  日期: {stockout_date_str}")
            logger.info(f"  备注: {note}")
            logger.info("-" * 60)

            # Step 4: 执行出库
            logger.info("执行出库操作...")
            result = await stock_service.create_stockout(
                db=db,
                product_id=product_id,
                quantity=quantity,
                customer=customer,
                stockout_date_str=stockout_date_str,
                note=note
            )

            # Step 5: 显示结果
            logger.info("✓ 出库操作完成！")
            logger.info(f"结果: {result}")

            # Step 6: 验证缓存失效（手动再次清理，确保万无一失）
            logger.info("")
            logger.info("清理 Dashboard 缓存...")
            await invalidate_cache('dashboard:*')
            await invalidate_cache('dashboard:stats')
            await invalidate_cache('dashboard:activities')
            logger.info("✓ Dashboard 缓存已清理")

            # Step 7: 再次发布事件（双重保险）
            logger.info("")
            logger.info("发布 WebSocket 实时通知...")
            try:
                # 重新获取产品信息（可能库存已更新）
                result = await db.execute(Product.__table__.select().where(Product.id == product_id))
                updated_product = result.first()

                await publish_stock_event(
                    event_type=StockEvent.STOCK_CHANGED,
                    data={
                        'product_id': product_id,
                        'product_name': updated_product.name,
                        'change_type': '出库',
                        'quantity': quantity,
                        'current_stock': updated_product.current_stock,
                        'simulated': True
                    }
                )
                logger.info("✓ WebSocket 事件已发布")
            except Exception as e:
                logger.warning(f"发布事件时出错（不影响数据）: {e}")

            # Step 8: 完成
            logger.info("")
            logger.info("=" * 60)
            logger.info("出库模拟完成！")
            logger.info("=" * 60)
            logger.info("")
            logger.info("现在请观察：")
            logger.info("  1. Dashboard 页面是否自动刷新")
            logger.info("  2. 出库总览数据是否更新")
            logger.info("  3. 浏览器控制台是否显示 '[WebSocket] 检测到数据变更'")
            logger.info("")

        except Exception as e:
            logger.error(f"出库操作失败: {e}", exc_info=True)
            await db.rollback()
            raise


async def simulate_multiple_stockouts(count: int = 3):
    """
    模拟多次出库操作（用于测试连续同步）

    Args:
        count: 出库次数
    """
    logger.info("=" * 60)
    logger.info(f"开始模拟 {count} 次出库操作...")
    logger.info("=" * 60)

    for i in range(count):
        logger.info("")
        logger.info(f"--- 第 {i+1} 次出库 ---")
        quantity = (i + 1) * 5
        await simulate_stockout(
            quantity=quantity,
            customer=f"批量测试客户 {i+1}",
            note=f"实时同步测试出库 #{i+1}"
        )
        if i < count - 1:
            # 每次出库间隔 3 秒
            logger.info("等待 3 秒后继续...")
            await asyncio.sleep(3)


def main():
    parser = argparse.ArgumentParser(
        description='出库操作模拟脚本 - 验证实时同步功能',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 基本用法（自动选择产品）
  python scripts/simulate_stockout.py

  # 指定产品
  python scripts/simulate_stockout.py --product-id 20409

  # 指定数量和客户
  python scripts/simulate_stockout.py --quantity 100 --customer "大客户A"

  # 批量测试（3次出库）
  python scripts/simulate_stockout.py --batch 3
        """
    )

    parser.add_argument(
        '--product-id', type=int, default=None,
        help='产品 ID（不指定则自动选择有库存的产品）'
    )
    parser.add_argument(
        '--quantity', type=int, default=10,
        help='出库数量（默认: 10）'
    )
    parser.add_argument(
        '--customer', type=str, default="实时同步测试客户",
        help='客户名称（默认: "实时同步测试客户"）'
    )
    parser.add_argument(
        '--note', type=str, default="实时同步功能验证测试",
        help='备注信息（默认: "实时同步功能验证测试"）'
    )
    parser.add_argument(
        '--batch', type=int, default=None,
        help='批量测试模式：执行指定次数的出库（示例: --batch 3）'
    )
    parser.add_argument(
        '--verbose', '-v', action='store_true',
        help='显示详细日志'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        if args.batch:
            # 批量模式
            asyncio.run(simulate_multiple_stockouts(count=args.batch))
        else:
            # 单次模式
            asyncio.run(simulate_stockout(
                product_id=args.product_id,
                quantity=args.quantity,
                customer=args.customer,
                note=args.note
            ))
    except KeyboardInterrupt:
        logger.info("用户中断")
    except Exception as e:
        logger.error(f"执行失败: {e}")
        return 1
    return 0


if __name__ == '__main__':
    from _prod_write_guard import require_prod_write_consent
    require_prod_write_consent('对生产库真实出库并扣减库存')
    sys.exit(main())
