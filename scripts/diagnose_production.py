#!/usr/bin/env python3
"""
生产数据诊断脚本
用于检查和修复生产数据卡片不显示的问题
"""

import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import asyncio

from sqlalchemy import func, select

from fastapi_app.core.database import _AsyncSessionLocal
from fastapi_app.shared_models import DailyProductionRecord


async def diagnose_production_data():
    """诊断生产数据问题"""
    print("=" * 70)
    print("              ERP 生产数据诊断工具")
    print("=" * 70)
    print()

    today = date.today()
    print(f"当前日期: {today}")
    print()

    async with _AsyncSessionLocal() as db:
        print("[1/5] 检查 DailyProductionRecord 表是否有数据...")

        # 检查所有记录
        count_all = await db.execute(select(func.count(DailyProductionRecord.id)))
        total_count = count_all.scalar() or 0
        print(f"    总记录数: {total_count}")

        if total_count == 0:
            print("    ❌ 没有找到任何生产记录！")
            print()
            print("    建议: 需要先生成一些测试数据")
            print()
            return

        # 检查今天的数据
        print()
        print("[2/5] 检查今日生产数据...")
        today_count = await db.execute(
            select(func.count(DailyProductionRecord.id))
            .where(func.extract('year', DailyProductionRecord.production_date) == today.year)
            .where(func.extract('month', DailyProductionRecord.production_date) == today.month)
            .where(func.extract('day', DailyProductionRecord.production_date) == today.day)
        )
        today_total = today_count.scalar() or 0
        print(f"    今日记录数: {today_total}")

        if today_total == 0:
            print("    ⚠️  今天没有生产数据，尝试查找本月数据...")

        # 检查本月数据
        print()
        print("[3/5] 检查本月生产数据...")
        month_count = await db.execute(
            select(func.count(DailyProductionRecord.id))
            .where(func.extract('year', DailyProductionRecord.production_date) == today.year)
            .where(func.extract('month', DailyProductionRecord.production_date) == today.month)
        )
        month_total = month_count.scalar() or 0
        print(f"    本月记录数: {month_total}")

        # 查看实际数据
        print()
        print("[4/5] 查看最近的生产记录...")
        recent = await db.execute(
            select(
                DailyProductionRecord.production_date,
                DailyProductionRecord.department,
                DailyProductionRecord.quantity,
                DailyProductionRecord.unit_price
            )
            .order_by(DailyProductionRecord.production_date.desc())
            .limit(10)
        )
        rows = recent.all()
        print(f"    最近 {len(rows)} 条记录:")
        for row in rows:
            print(f"      - {row.production_date or 'N/A'} | {row.department or 'N/A'} | {row.quantity}件 | ¥{row.unit_price}")

        # 汇总部门数据
        print()
        print("[5/5] 检查部门汇总数据...")
        dept_result = await db.execute(
            select(
                DailyProductionRecord.department,
                func.coalesce(func.sum(DailyProductionRecord.quantity), 0),
                func.coalesce(func.sum(DailyProductionRecord.quantity * DailyProductionRecord.unit_price), 0)
            )
            .group_by(DailyProductionRecord.department)
            .limit(5)
        )
        dept_rows = dept_result.all()
        print(f"    共有 {len(dept_rows)} 个部门有数据:")
        for row in dept_rows:
            print(f"      - {row[0] or 'N/A'}: {row[1]}件, ¥{row[2]}")

        print()
        print("=" * 70)
        print("诊断完成！")
        print("=" * 70)


async def create_test_production_data():
    """创建测试生产数据"""
    print("=" * 70)
    print("              生成测试生产数据")
    print("=" * 70)
    print()

    today = date.today()

    async with _AsyncSessionLocal() as db:
        # 检查是否已有今天的数据
        check = await db.execute(
            select(func.count(DailyProductionRecord.id))
            .where(func.extract('year', DailyProductionRecord.production_date) == today.year)
            .where(func.extract('month', DailyProductionRecord.production_date) == today.month)
            .where(func.extract('day', DailyProductionRecord.production_date) == today.day)
        )

        if check.scalar() > 0:
            print("⚠️  今天已有数据，跳过创建")
            return

        # 创建测试数据
        test_data = [
            {'department': 'filling', 'quantity': 500, 'unit_price': 25.0, 'product_name': '鲨鱼'},
            {'department': 'handcraft', 'quantity': 300, 'unit_price': 18.0, 'product_name': '小狗'},
            {'department': 'packaging', 'quantity': 800, 'unit_price': 12.0, 'product_name': '小猫'},
        ]

        from sqlalchemy import insert

        for data in test_data:
            stmt = insert(DailyProductionRecord).values(
                production_date=today,
                department=data['department'],
                quantity=data['quantity'],
                unit_price=data['unit_price'],
                product_id=20409,  # 使用鲨鱼产品
                product_name=data['product_name'],
                barcode='',
                create_time=datetime.now()
            )
            await db.execute(stmt)

        await db.commit()

        print("✅ 测试数据已创建！")
        print(f"   日期: {today}")
        print("   充棉部: 500件 × ¥25.0 = ¥12,500")
        print("   手工部: 300件 × ¥18.0 = ¥5,400")
        print("   包装部: 800件 × ¥12.0 = ¥9,600")
        print("   总计: ¥27,500")
        print()
        print("请刷新 Dashboard 页面查看效果！")


if __name__ == '__main__':
    # 按「是否出现」判定，不看 argv[1] 位置：`... --allow-prod-write --create-test`
    # 这种带前置参数时，原先会漏判成只读分支（静默不写、也不报护栏）。
    # 带值形态只认**真值**（`--create-test=1|true|yes`）—— 若把 `--create-test=0/false`
    # 也算启用，等于把"明确表示别写"翻成写库分支（方向更危险）。
    _argv = sys.argv[1:]
    if '--create-test' in _argv or any(
        a.split('=', 1)[1].strip().lower() in ('1', 'true', 'yes', 'on')
        for a in _argv if a.startswith('--create-test=')
    ):
        # 只有这一支写库（else 是只读诊断，不加护栏）
        from _prod_write_guard import require_prod_write_consent
        require_prod_write_consent('向生产库插入测试生产记录（--create-test）')
        asyncio.run(create_test_production_data())
    else:
        asyncio.run(diagnose_production_data())
