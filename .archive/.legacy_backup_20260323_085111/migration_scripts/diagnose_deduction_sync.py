#!/usr/bin/env python
"""
备货抵扣同步问题诊断脚本
用于验证问题的根本原因
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import StockIn, StockOut, app


def diagnose_issue():
    """诊断备货抵扣同步问题"""
    print("=" * 70)
    print("备货抵扣同步问题诊断")
    print("=" * 70)

    with app.app_context():
        print("\n【问题分析】")
        print("-" * 70)

        # 1. 检查StockIn模型结构
        print("\n1. StockIn模型字段分析:")
        print("   - id: 主键")
        print("   - stockin_no: 备货编号")
        print("   - quantity: 备货数量（原始值，不会被抵扣修改）")
        print("   - stockouts: 关联的抵扣记录列表")

        # 2. 检查抵扣逻辑
        print("\n2. 订单抵扣逻辑分析:")
        print("   当订单创建并抵扣备货时:")
        print("   - 创建StockOut记录，设置stockin_id指向被抵扣的StockIn")
        print("   - StockOut.quantity = 抵扣数量")
        print("   - StockIn.quantity 保持不变（这是正确的）")
        print("   - Product.current_stock 减少抵扣数量")

        # 3. 检查备货管理页面的计算逻辑
        print("\n3. 备货管理页面计算逻辑分析:")
        print("   剩余数量 = total_quantity - total_deducted")
        print("   其中:")
        print("   - total_quantity = 累加所有StockIn.quantity")
        print("   - total_deducted = 累加所有StockOut.quantity（通过stockouts关联）")

        # 4. 实际数据验证
        print("\n4. 实际数据验证:")
        print("-" * 70)

        stockins = StockIn.query.all()
        if stockins:
            for stockin in stockins:
                print(f"\n   备货记录: {stockin.stockin_no}")
                print(f"   - 原始数量: {stockin.quantity}")

                # 计算已抵扣数量
                deducted = sum(so.quantity for so in stockin.stockouts) if stockin.stockouts else 0
                remaining = stockin.quantity - deducted

                print(f"   - 已抵扣数量: {deducted}")
                print(f"   - 剩余数量: {remaining}")
                print(f"   - stockouts记录数: {len(stockin.stockouts) if stockin.stockouts else 0}")

                if stockin.stockouts:
                    for so in stockin.stockouts:
                        print(f"     → StockOut: {so.stockout_no}, 数量: {so.quantity}, 关联订单: {so.order_id}")
        else:
            print("   暂无备货记录")

        # 5. 检查是否有孤立的StockOut记录
        print("\n5. 检查孤立的StockOut记录:")
        print("-" * 70)
        orphan_stockouts = StockOut.query.filter(StockOut.stockin_id is None).all()
        if orphan_stockouts:
            print(f"   [!] 发现 {len(orphan_stockouts)} 条孤立记录（stockin_id为空）:")
            for so in orphan_stockouts:
                print(f"     - {so.stockout_no}, 数量: {so.quantity}")
        else:
            print("   [OK] 无孤立记录，所有StockOut都正确关联到StockIn")

        # 6. 检查分组计算
        print("\n6. 分组计算验证:")
        print("-" * 70)
        from collections import OrderedDict

        from sqlalchemy.orm import joinedload

        stockins_with_relations = StockIn.query.options(
            joinedload(StockIn.product),
            joinedload(StockIn.stockouts).joinedload(StockOut.order)
        ).all()

        grouped = OrderedDict()
        for stockin in stockins_with_relations:
            key = (stockin.customer, stockin.product_id)

            if key not in grouped:
                grouped[key] = {
                    'customer': stockin.customer,
                    'product': stockin.product.name if stockin.product else 'N/A',
                    'total_quantity': 0,
                    'total_deducted': 0,
                }

            grouped[key]['total_quantity'] += stockin.quantity

            if stockin.stockouts:
                for stockout in stockin.stockouts:
                    grouped[key]['total_deducted'] += stockout.quantity

        for key, group in grouped.items():
            remaining = group['total_quantity'] - group['total_deducted']
            print(f"\n   分组: 客户={group['customer']}, 产品={group['product']}")
            print(f"   - 总数量: {group['total_quantity']}")
            print(f"   - 已抵扣: {group['total_deducted']}")
            print(f"   - 剩余数量: {remaining}")

        # 7. 结论
        print("\n" + "=" * 70)
        print("【诊断结论】")
        print("=" * 70)
        print("""
根据代码分析，系统设计是正确的：

1. StockIn.quantity 存储原始备货数量，不会被抵扣修改
2. StockOut记录通过stockin_id关联到StockIn
3. 备货管理页面通过 stockin.stockouts 关联查询抵扣记录
4. 剩余数量 = total_quantity - total_deducted

可能的问题原因：
1. 数据库查询缓存问题
2. 前端页面未刷新
3. SQLAlchemy会话缓存问题
4. joinedload预加载时机问题

建议的修复方案：
1. 确保查询时使用新鲜的会话
2. 添加查询刷新机制
3. 验证stockouts关联是否正确加载
        """)

if __name__ == '__main__':
    diagnose_issue()
