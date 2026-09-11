#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
库存多年期模拟 —— 幂等清理

删除指定 SIMTEST- 客户的全部出库/入库/订单记录，并删除（或清零）测试产品。
重复执行输出"无待清理项"（幂等）。默认只列出待清理项，--confirm 才实际执行。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import SimAPIClient  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("stock_sim.cleanup")


def resolve_journal(run_dir: str) -> str:
    if run_dir and run_dir not in ("latest", "."):
        return run_dir.rstrip("/")
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "journal")
    if not os.path.isdir(base):
        raise SystemExit(f"journal 目录不存在: {base}")
    subs = sorted(
        (os.path.join(base, d) for d in os.listdir(base)
         if os.path.isdir(os.path.join(base, d))),
        key=lambda p: os.path.getmtime(p), reverse=True,
    )
    if not subs:
        raise SystemExit(f"journal 下无任何 run: {base}")
    return subs[0]


def load_targets(args) -> tuple[str | None, int | None]:
    customer, product_id = args.customer, args.product_id
    if args.journal:
        run_dir = resolve_journal(args.journal)
        summary_p = os.path.join(run_dir, "summary.json")
        if os.path.exists(summary_p):
            with open(summary_p, "r", encoding="utf-8") as f:
                summary = json.load(f)
            customer = customer or summary.get("customer")
            product_id = product_id or summary.get("product_id")
    return customer, product_id


async def cleanup(client: SimAPIClient, customer: str | None,
                  product_id: int | None, confirm: bool):
    if not customer and not product_id:
        print("未提供 customer 或 product_id，无清理目标")
        return
    removed_out = removed_in = removed_order = 0

    # 1) 出库（先删，避免入库有出库关联删不掉）
    if customer:
        outs = await client.stockout_list(customer)
        removed_out = len(outs)
        print(f"待删出库 {removed_out} 条")
        if confirm:
            for o in outs:
                await client.delete_stockout(o["id"])
            print(f"已删出库 {removed_out} 条")
    # 2) 入库
    if customer:
        ins = await client.stockin_list(customer)
        removed_in = len(ins)
        print(f"待删入库 {removed_in} 条")
        if confirm:
            for i in ins:
                await client.delete_stockin(i["id"])
            print(f"已删入库 {removed_in} 条")
    # 3) 订单
    if customer:
        orders = await client.order_list(customer)
        removed_order = len(orders)
        print(f"待删订单 {removed_order} 条")
        if confirm:
            for o in orders:
                await client.delete(f"/orders/delete/{o['id']}")
            print(f"已删订单 {removed_order} 条")
    # 4) 产品
    if product_id:
        pc = await client.product_available_stock(product_id)
        cur = pc.get("current_stock")
        print(f"产品 {product_id} 当前库存: {cur}")
        if confirm:
            ok = await client.delete_product(product_id)
            if not ok:
                print(f"警告：产品删除失败，请人工确认（空库则直接删除 product 表行）。")

    if removed_out == removed_in == removed_order == 0 and not confirm:
        print("无待清理项（幂等确认）")


async def main():
    ap = argparse.ArgumentParser(description="库存模拟清理器")
    ap.add_argument("--journal", default=None, help="journal 目录或 'latest'")
    ap.add_argument("--customer", default=None)
    ap.add_argument("--product-id", type=int, default=None)
    ap.add_argument("--confirm", action="store_true", dest="confirm")
    args = ap.parse_args()

    import getpass
    username = os.environ.get("ERP_SIM_USER")
    password = os.environ.get("ERP_SIM_PASSWORD")
    if not username or not password:
        username = input("用户名: ")
        password = getpass.getpass("密码: ")

    customer, product_id = load_targets(args)
    if not args.confirm:
        print("（预览模式，未真正删除。加 --confirm 执行。目标如下）")
    client = SimAPIClient(username, password)
    await client.login()
    await cleanup(client, customer, product_id, args.confirm)
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())