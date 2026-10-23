"""生成「单日多条计划」测试数据，用于验证排产日历的卡片折叠展示。

背景：日历卡片的数据来自 monthly-aggregated 的 sku_date_index，其按
「客户|产品」去重聚合。因此要让某一天出现多条，必须在**同一天**写入
多个不同的（客户, 产品）组合 —— 同一组合的多条明细会被合并成 1 行。

目标月份：2026-10（当前为空月份）。落库内容：
    2026-10-08  5 条组合 / 3 家客户  → 触发折叠（显示 3 条 + 还有 2 条）
    2026-10-15  4 条组合 / 2 家客户  → 触发折叠（显示 3 条 + 还有 1 条）
    2026-10-22  3 条组合 / 2 家客户  → 恰好等于上限，不折叠
    2026-10-28  1 条组合 / 1 家客户  → 基线，不折叠

用法：
    python scripts/create_purchase_plan_multi_per_day.py            # 写入
    python scripts/create_purchase_plan_multi_per_day.py --cleanup  # 删除本脚本写入的数据
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date

from sqlalchemy import delete, select

from fastapi_app.core.database import SyncSessionLocal
from fastapi_app.services.purchase_plan_common import _invalidate_plan_caches
from fastapi_app.shared_models.purchase_plan import PurchasePlan, PurchasePlanDetail

TARGET_MONTH = '2026-10'
# 本脚本写入的 plan_no 前缀，cleanup 与重复写入检测都依赖它
PLAN_NO_PREFIX = 'PP-20261001-'
SEED_TAG = '[TEST]单日多条计划-日历折叠验证'

PRODUCTS = {
    'penguin': (20422, '企鹅', '6941377414684'),
    'penguin_pink': (20430, '10寸企鹅公仔(粉色)', ''),
    'nommi': (20534, 'Nommi糯米儿-宝藏收藏家系列毛绒盲盒', '6978946330588'),
    'transformer': (20541, '变形金刚', ''),
    'sister2': (20533, '妹妹二代', '6978946330580'),
    'hamster_pink': (20427, '10寸仓鼠毛绒公仔(粉色)', ''),
    'penguin_x3': (20535, '企鹅企鹅企鹅', '6978946330581'),
}

CUSTOMERS = {
    'miniso_intl': (20182, 'MINISO国际'),
    'miniso_cn': (20183, 'MINISO国内'),
    'top_toy': (20184, 'TOP TOY'),
    'netease': (20248, '网易严选'),
    'aofei': (20249, '奥飞'),
}

# (日期, [(客户key, [(产品key, 数量)]), ...])
SEED_DAYS = [
    ('2026-10-08', [
        ('miniso_intl', [('penguin', 1200), ('transformer', 800)]),
        ('netease', [('penguin_pink', 666)]),
        ('aofei', [('nommi', 999), ('sister2', 300)]),
    ]),
    ('2026-10-15', [
        ('miniso_intl', [('penguin', 2000), ('penguin_x3', 1500), ('transformer', 500)]),
        ('top_toy', [('hamster_pink', 400)]),
    ]),
    ('2026-10-22', [
        ('miniso_cn', [('penguin', 700), ('nommi', 300)]),
        ('netease', [('transformer', 200)]),
    ]),
    ('2026-10-28', [
        ('miniso_intl', [('penguin', 500)]),
    ]),
]


def _assert_target_month_empty(session) -> None:
    """目标月份已有数据时中止，避免污染或重复写入。"""
    existing = session.execute(
        select(PurchasePlan.plan_no).where(PurchasePlan.plan_month == TARGET_MONTH)
    ).scalars().all()
    if existing:
        raise SystemExit(
            f'[ABORT] {TARGET_MONTH} 已存在 {len(existing)} 个计划：{existing}。\n'
            f'        请先执行 --cleanup，或确认这些数据可以共存后再手动处理。'
        )


def _next_plan_seq(session) -> int:
    """从本脚本前缀的历史编号推导下一个序号。"""
    rows = session.execute(
        select(PurchasePlan.plan_no).where(PurchasePlan.plan_no.like(f'{PLAN_NO_PREFIX}%'))
    ).scalars().all()
    seqs = []
    for no in rows:
        tail = no.rsplit('-', 1)[-1]
        if tail.isdigit():
            seqs.append(int(tail))
    return max(seqs, default=0) + 1


def seed() -> None:
    session = SyncSessionLocal()
    try:
        _assert_target_month_empty(session)
        seq = _next_plan_seq(session)
        plan_count = 0
        detail_count = 0

        for day_str, groups in SEED_DAYS:
            plan_date = date.fromisoformat(day_str)
            for cust_key, items in groups:
                customer_id, customer_name = CUSTOMERS[cust_key]
                plan_no = f'{PLAN_NO_PREFIX}{seq:04d}'
                seq += 1

                plan = PurchasePlan(
                    plan_no=plan_no,
                    plan_month=TARGET_MONTH,
                    customer_id=customer_id,
                    customer_name=customer_name,
                    status='pending',
                    remark=SEED_TAG,
                    created_by='seed_script',
                )
                session.add(plan)
                session.flush()
                plan_count += 1

                for prod_key, qty in items:
                    product_id, product_name, barcode = PRODUCTS[prod_key]
                    session.add(PurchasePlanDetail(
                        plan_id=plan.id,
                        product_id=product_id,
                        product_name=product_name,
                        barcode=barcode,
                        plan_date=plan_date,
                        quantity=qty,
                        shipped_qty=0,
                        remark=SEED_TAG,
                    ))
                    detail_count += 1

                print(f'  {day_str} | {plan_no} | {customer_name:12s} | {len(items)} 条明细')

        session.commit()
        print(f'\n[OK] 已写入 {plan_count} 个计划 / {detail_count} 条明细，月份={TARGET_MONTH}')

        # 汇总每个日期的「客户|产品」组合数，直观确认折叠会触发在哪几天
        print('\n各日期组合数（>3 会触发折叠）：')
        for day_str, groups in SEED_DAYS:
            combos = sum(len(items) for _, items in groups)
            custs = len(groups)
            flag = '← 折叠' if combos > 3 else ''
            print(f'  {day_str}  {combos} 条组合 / {custs} 家客户 {flag}')
    finally:
        session.close()


def cleanup() -> None:
    session = SyncSessionLocal()
    try:
        plan_ids = session.execute(
            select(PurchasePlan.id).where(PurchasePlan.plan_no.like(f'{PLAN_NO_PREFIX}%'))
        ).scalars().all()
        if not plan_ids:
            print('[INFO] 未找到本脚本写入的数据，无需清理')
            return
        session.execute(delete(PurchasePlanDetail).where(PurchasePlanDetail.plan_id.in_(plan_ids)))
        session.execute(delete(PurchasePlan).where(PurchasePlan.id.in_(plan_ids)))
        session.commit()
        print(f'[OK] 已删除 {len(plan_ids)} 个计划及其明细')
    finally:
        session.close()


async def refresh_cache() -> None:
    """清理月份聚合缓存，避免页面读到 120s TTL 内的旧结果。"""
    try:
        await _invalidate_plan_caches(TARGET_MONTH)
        print('[OK] 已清理 pp:agg / pp:day 缓存')
    except Exception as e:  # 缓存后端不可用不应阻断数据写入
        print(f'[WARN] 缓存清理失败（不影响数据落库，可等待 TTL 过期）：{e}')


def main() -> None:
    # P1（2026-10-24）：本脚本往生产业务表写 13 条假计划，必须与同目录的
    # create_test_orders.py / seed_pattern_room.py 一样过生产写授权。
    from _prod_write_guard import require_prod_write_consent

    if '--cleanup' in sys.argv:
        require_prod_write_consent('清理测试采购计划（删除 SEED_TAG 数据）')
        cleanup()
    else:
        require_prod_write_consent(
            '写入 13 条测试采购计划到 purchase_plans / purchase_plan_details',
            hint='本机即生产：跑完请用 --cleanup 回收，否则采购员会当成真实需求排产。',
        )
        seed()
    asyncio.run(refresh_cache())


if __name__ == '__main__':
    main()
