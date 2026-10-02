"""PostgreSQL advisory lock 工具（编号与业务锁共用）。

随编号生成内核统一独立成模块：旧编号生成器删除后，CASE 创建锁等业务用途
仍需要同一把事务级 advisory lock。md5 取键方案保持不变，lock key 与
迁移前逐位一致，无运行时行为变更。
"""
import hashlib
import logging

from sqlalchemy import func, select
from sqlalchemy.exc import ProgrammingError

logger = logging.getLogger(__name__)


def number_lock_key(scope: str, key: str) -> int:
    """为 (scope, key) 生成 PostgreSQL advisory lock key。

    取 md5 前 **15** 个十六进制位 = **60 位**（原注释写「64 位」，与实际不符）。
    刻意不取满 16 位：16 位最大可到 2^64-1，会超出 pg_advisory_xact_lock 的
    bigint（int8，上限 2^63-1）而报错；60 位仍在范围内、碰撞概率可忽略。

    ⚠️ 拼接分隔符**必须保持 ':'**：`f"{scope}:{key}"` 的取值被
    tests/test_pg_locks.py::test_number_lock_key_value_unchanged_from_legacy 钉死。
    改成 NUL 之类的"更无歧义"分隔符会让**滚动发布期间新旧进程算出不同的锁键、
    互斥静默失效**。`("a","b:c")` 与 `("a:b","c")` 撞键只是理论隐患，当前调用方
    （CASE_PRODUCT/str(product_id)、NUMBERING_RECONCILE/'startup'）不含 ':'。
    """
    raw = f"{scope}:{key}".encode()
    hex_key = hashlib.md5(raw, usedforsecurity=False).hexdigest()[:15]
    return int(hex_key, 16)


async def acquire_advisory_lock_async(db, lock_key: int) -> None:
    """获取 PostgreSQL 事务级 advisory lock；非 PG 环境则忽略。

    只吞 `ProgrammingError`（函数不存在 —— 非 PG 或测试替身）。原先吞 `Exception`
    会把**真实 PG 错误**（锁等待超时、串行化失败等）也降级为"无锁"继续执行，
    而编号生成/对账依赖这把锁 —— 并发下会重号。其余异常照常抛出。
    """
    try:
        await db.execute(select(func.pg_advisory_xact_lock(lock_key)))
    except ProgrammingError as e:
        logger.debug("advisory lock 不可用（非 PG 环境？），降级为无锁模式: %s", e)
