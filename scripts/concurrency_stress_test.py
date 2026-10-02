#!/usr/bin/env python3
"""高并发压测脚本：多进程同时生成编号并扣减库存

用法示例：
    python scripts/concurrency_stress_test.py --product-id 1 --workers 8 --iterations 100

注意事项：
- 默认会写入 order/stock_out 表并使用特殊前缀（STRESS-YYYYMMDD-XXXX），测试结束后自动清理。
- 请确保使用测试数据库，或确认不会误删正式数据。
"""
from __future__ import annotations

import argparse
import asyncio
import multiprocessing
import os
import sys
import time
from datetime import UTC, datetime
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sqlalchemy import delete

from fastapi_app.core.database import get_async_db_context
from fastapi_app.services.numbering import generate_number_async
from fastapi_app.shared.stock_concurrency import update_stock_with_optimistic_lock
from fastapi_app.shared_models import Order, Product, StockOut

# model_name -> (model_cls, date_field, number_field)
MODEL_CONFIG: dict[str, tuple[Any, str, str]] = {
    "order": (Order, "order_date", "order_no"),
    "stockout": (StockOut, "stockout_date", "stockout_no"),
}


async def reset_product_stock(product_id: int, total_needed: int) -> int:
    """为压测预置足够库存并归零版本号，避免历史 version 干扰。"""
    async with get_async_db_context() as db:
        product = await db.get(Product, product_id)
        if product is None:
            raise RuntimeError(f"产品 ID {product_id} 不存在")
        product.current_stock = total_needed
        product.version = 0
        await db.commit()
        return product.current_stock


async def verify_product_stock(product_id: int, expected: int) -> tuple[int, int]:
    """返回压测后产品实际库存与 version，用于校验扣减是否丢失。"""
    async with get_async_db_context() as db:
        product = await db.get(Product, product_id)
        if product is None:
            raise RuntimeError(f"产品 ID {product_id} 不存在")
        return product.current_stock, product.version


async def _generate_and_insert_once(
    prefix: str,
    model_name: str,
    product_id: int,
) -> tuple[str, int]:
    """在独立事务内生成编号并写入对应表，确保编号不重复。"""
    model_cls, _date_field, number_field = MODEL_CONFIG[model_name]
    async with get_async_db_context() as db:
        number = await generate_number_async(prefix, model_cls, number_field, db)
        if model_name == "order":
            record = Order(
                order_no=number,
                customer="stress-test",
                order_date=datetime.now(UTC),
                product_id=product_id,
                quantity=1,
                status="待备货",
            )
        else:
            record = StockOut(
                stockout_no=number,
                stockout_date=datetime.now(UTC),
                product_id=product_id,
                quantity=1,
                customer="stress-test",
            )
        db.add(record)
        await db.flush()
        record_id = record.id
        await db.commit()
        return number, record_id


async def _deduct_stock_once(product_id: int, delta: int) -> tuple[bool, Exception | None]:
    """使用 version 乐观锁扣减一次库存。"""
    async with get_async_db_context() as db:
        try:
            await update_stock_with_optimistic_lock(db, product_id, delta)
            await db.commit()
            return True, None
        except Exception as exc:  # defensive: 统计并发/库存不足等异常
            await db.rollback()
            return False, exc


async def worker(
    worker_name: str,
    args: argparse.Namespace,
    result_queue: multiprocessing.Queue,
) -> None:
    """单个工作进程：循环执行编号生成与库存扣减。"""
    numbers: list[str] = []
    created_ids: list[tuple[str, int]] = []
    number_success = 0
    number_errors = 0
    stock_success = 0
    stock_errors = 0
    first_stock_error: Exception | None = None

    for _ in range(args.iterations):
        if not args.stock_only:
            try:
                number, record_id = await _generate_and_insert_once(
                    args.number_prefix, args.number_model, args.product_id
                )
                numbers.append(number)
                created_ids.append((args.number_model, record_id))
                number_success += 1
            except Exception as exc:  # defensive: 压测脚本记录异常而非中断
                number_errors += 1
                if number_errors <= 3:
                    print(f"[{worker_name}] 编号生成异常: {exc}")

        if not args.number_only:
            ok, exc = await _deduct_stock_once(args.product_id, args.deduct_delta)
            if ok:
                stock_success += 1
            else:
                stock_errors += 1
                if first_stock_error is None:
                    first_stock_error = exc
                if stock_errors <= 3:
                    print(f"[{worker_name}] 库存扣减异常: {exc}")

    result_queue.put(
        {
            "numbers": numbers,
            "created_ids": created_ids,
            "number_success": number_success,
            "number_errors": number_errors,
            "stock_success": stock_success,
            "stock_errors": stock_errors,
            "first_stock_error": str(first_stock_error) if first_stock_error else None,
        }
    )


def run_worker(worker_name: str, args: argparse.Namespace, result_queue: multiprocessing.Queue) -> None:
    asyncio.run(_worker_async(worker_name, args, result_queue))


async def _worker_async(worker_name: str, args: argparse.Namespace, result_queue: multiprocessing.Queue) -> None:
    """子进程入口：先执行业务循环，再释放连接池，最后上报结果。"""
    try:
        await worker(worker_name, args, result_queue)
    finally:
        # 子进程独立引擎，退出前释放连接池，避免进程结束时事件循环已关闭的警告
        from fastapi_app.core.database import async_engine

        if async_engine is not None:
            await async_engine.dispose()


async def cleanup_records(created_ids: list[tuple[str, int]]) -> int:
    """按收集到的主键删除压测产生的订单/出货记录。"""
    if not created_ids:
        return 0
    order_ids = [rid for model_name, rid in created_ids if model_name == "order"]
    stockout_ids = [rid for model_name, rid in created_ids if model_name == "stockout"]

    async with get_async_db_context() as db:
        if order_ids:
            await db.execute(delete(Order).where(Order.id.in_(order_ids)))
        if stockout_ids:
            await db.execute(delete(StockOut).where(StockOut.id.in_(stockout_ids)))
        await db.commit()
    return len(order_ids) + len(stockout_ids)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="高并发压测：编号生成 + 库存扣减")
    parser.add_argument("--workers", type=int, default=8, help="并发进程数（默认 8）")
    parser.add_argument("--iterations", type=int, default=100, help="每个进程迭代次数（默认 100）")
    parser.add_argument("--product-id", type=int, required=True, help="用于扣减库存的产品 ID")
    parser.add_argument(
        "--number-prefix", default="STRESS", help="编号前缀（默认 STRESS）"
    )
    parser.add_argument(
        "--number-model",
        choices=["order", "stockout"],
        default="order",
        help="编号写入的表（默认 order）",
    )
    parser.add_argument(
        "--deduct-delta", type=int, default=-1, help="每次库存变动量（默认 -1）"
    )
    parser.add_argument("--number-only", action="store_true", help="仅执行编号生成")
    parser.add_argument("--stock-only", action="store_true", help="仅执行库存扣减")
    parser.add_argument("--skip-cleanup", action="store_true", help="测试结束后不清理写入的数据")
    parser.add_argument('--allow-prod-write', action='store_true',
                        help='显式授权写生产库（与 ERP_ALLOW_PROD_WRITE=1 等价）')

    args = parser.parse_args()

    if args.number_only and args.stock_only:
        parser.error("--number-only 和 --stock-only 不能同时指定")
    return args


def _spawn_and_join(args: argparse.Namespace, result_queue: multiprocessing.Queue) -> None:
    """同步函数：启动所有子进程并等待结束。"""
    processes: list[multiprocessing.Process] = []
    for i in range(args.workers):
        p = multiprocessing.Process(
            target=run_worker,
            args=(f"worker-{i}", args, result_queue),
        )
        p.start()
        processes.append(p)
    for p in processes:
        p.join()


def _collect_results(result_queue: multiprocessing.Queue, count: int) -> list[dict]:
    """同步函数：收集所有子进程上报结果。"""
    return [result_queue.get() for _ in range(count)]


async def async_main(args: argparse.Namespace) -> int:
    """主流程：所有数据库操作在同一个事件循环内完成，避免跨 loop 复用引擎连接池。"""
    total_ops = args.workers * args.iterations
    expected_deduction = total_ops if not args.number_only else 0

    if not args.number_only:
        initial_stock = expected_deduction + 1000
        print(f"预置产品 {args.product_id} 库存为 {initial_stock}")
        await reset_product_stock(args.product_id, initial_stock)

    result_queue: multiprocessing.Queue = multiprocessing.Queue()

    start = time.perf_counter()
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _spawn_and_join, args, result_queue)
    elapsed = time.perf_counter() - start

    results = await loop.run_in_executor(None, _collect_results, result_queue, args.workers)

    all_numbers: list[str] = []
    all_ids: list[tuple[str, int]] = []
    agg = {
        "number_success": 0,
        "number_errors": 0,
        "stock_success": 0,
        "stock_errors": 0,
    }
    first_error_messages: list[str] = []

    for result in results:
        all_numbers.extend(result["numbers"])
        all_ids.extend(result["created_ids"])
        for key in agg:
            agg[key] += result[key]
        if result["first_stock_error"]:
            first_error_messages.append(result["first_stock_error"])

    unique_numbers = set(all_numbers)
    duplicates = len(all_numbers) - len(unique_numbers)

    print("\n========== 压测结果 ==========")
    print(f"进程数: {args.workers}, 每进程迭代: {args.iterations}")
    print(f"总耗时: {elapsed:.3f}s, 整体 QPS: {total_ops / elapsed:.1f}")
    print(
        f"编号生成: 成功 {agg['number_success']}, 失败 {agg['number_errors']}, "
        f"总数 {len(all_numbers)}, 唯一 {len(unique_numbers)}, 重复 {duplicates}"
    )
    print(
        f"库存扣减: 成功 {agg['stock_success']}, 失败 {agg['stock_errors']}"
    )
    if first_error_messages:
        print(f"首个库存异常示例: {first_error_messages[0]}")

    if not args.number_only:
        final_stock, final_version = await verify_product_stock(
            args.product_id, expected_deduction
        )
        print(f"压测后库存: {final_stock}, version: {final_version}")
        expected_stock = (expected_deduction + 1000) + expected_deduction * args.deduct_delta
        if final_stock != expected_stock:
            print(f"库存校验失败: 期望 {expected_stock}, 实际 {final_stock}")

    if not args.skip_cleanup and all_ids:
        deleted = await cleanup_records(all_ids)
        print(f"已清理压测数据: {deleted} 条")

    if duplicates or agg["stock_errors"]:
        print("\n结果：未通过（存在编号重复或库存扣减失败）")
        return 1
    print("\n结果：通过（无编号重复，库存扣减无并发失败）")
    return 0


def main() -> None:
    args = _parse_args()
    sys.exit(asyncio.run(async_main(args)))


if __name__ == "__main__":
    from _prod_write_guard import require_prod_write_consent
    require_prod_write_consent('压测：改写生产产品库存且不还原')
    main()
