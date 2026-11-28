"""库存只读对账（P1-1）：``inventory_log`` 聚合 vs ``product.current_stock``。

背景：``docs/optimization-plan-2026-10-01-round3.md:160``（P1-1）指出库存余额有 54 处就地
写点、流水 26 处构造点，而 ``shared_models/inventory_log.py`` 只记位移、不记结存，因此
「余额是否等于流水累计」此前无从判定。本模块提供**只读**对账，先把漂移量化成报告与差异
清单，再谈 P1-6 的 ``CHECK(current_stock >= 0)``。

对账口径：``expected = COALESCE(SUM(inventory_log.change_quantity), 0)``（按
``product_id`` 分组；无流水的产品取 0），``diff = current_stock - expected``：
``diff == 0`` → ``matched``；``diff > 0`` → ``positive``（账面高于流水）；
``diff < 0`` → ``negative``（账面低于流水）。

已知的非缺陷性差异来源（按 ``positive`` 计入报告，不自动修）：批量导入产品时
``services/batch_import_core.py:309-316`` 直接落 ``Product(initial_stock=stock,
current_stock=stock)`` 而不写 ``InventoryLog``；只有 ``services/product_service.py``
的建品 / 改初始库存会写「初始库存 / 初始库存调整」流水。

只读契约：本模块对 ``inventory_log`` 与 ``product`` 只发 SELECT（单条 GROUP BY
集合式查询，无逐产品查询即无 N+1），不 add / delete / flush / commit。
``fastapi_app/tests/test_inventory_reconcile.py`` 用 AST 断言锁死这一点。
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.shared_models import InventoryLog, Product

#: 低频 cron 时刻：每日 03:30（避开 02:00 全量备份、03:00 增量备份与 04:30 日志维护）。
CRON_HOUR = 3
CRON_MINUTE = 30
#: 差异明细默认上限（``diff_count`` 与 ``truncated`` 仍如实反映全量）。
DEFAULT_DIFF_LIMIT = 200

STATUS_MATCHED = 'matched'
STATUS_POSITIVE = 'positive'
STATUS_NEGATIVE = 'negative'

#: **只登记「订单需求」、不代表物理库存变动**的 change_type：对账时必须排除。
#:
#: 对账期望值是 ``SUM(change_quantity)``，而物理库存只由走统一写入口
#: （``apply_stock_delta_locked`` / ``update_stock_with_optimistic_lock``）的写点
#: 改变。下列类型把「客户要多少」记进流水但**不动** ``product.current_stock``，
#: 计入 SUM 会让每个有订单的产品永久负漂移（订单越多账面越低）。
#:
#: 逐个核对过的写入点（2026-11-15 审计，``grep -rn "change_type" fastapi_app``）：
#:   - ``订单``：``services/order/commands.py`` create_order（docstring 明示「不影响
#:     物理库存」）、``services/batch_import_core.py:870``（注释写明订单不改库存）、
#:     ``services/batch_import_service.py:418``、``services/staging/order.py:190``
#:     （2026-10-24 P0 已删掉该处 +quantity 的库存写）——四处均无库存写调用；
#:   - ``订单创建``：``services/order_batch_create.py``、``tasks/batch_tasks.py:293``
#:     ——同文件 0 处 ``current_stock`` / ``apply_stock_delta_locked``；
#:   - ``订单修改``：``services/order/commands.py``（明细改量 / 明细删除 / 整单改量）
#:     ——该文件全篇无库存写调用；
#:   - ``订单修改(审批)``：历史审批路径写入（审批系统已于 2026-11-28 下线，仅存量流水）；
#:   - ``订单删除``：``shared/order_stock_rollback.py:113`` 的订单级汇总行——真实物理
#:     变动已由同函数逐个产品的 ``抵扣回滚`` 行（``apply_stock_delta_locked``）记账，
#:     这行是同额汇总，计入即重复计数；
#:   - ``订单删除(审批)``：同上（历史审批删单自写汇总；审批系统已下线，仅存量流水）。
#:
#: 刻意**不**排除的相邻类型（它们真的改了 ``current_stock``，排除会造成反向漂移）：
#: ``订单抵扣`` / ``取消抵扣``（``services/order/deduction.py``、
#: ``services/order_deduction_service.py`` 都调 ``update_stock_with_optimistic_lock``）、
#: ``抵扣回滚``（``shared/order_stock_rollback.py:97`` 走 ``apply_stock_delta_locked``）、
#: ``备货`` / ``备货入库`` / ``出库`` / ``入库*`` / ``退货*`` / ``生产入库*`` / ``初始库存*``。
DEMAND_ONLY_CHANGE_TYPES: tuple[str, ...] = (
    '订单',
    '订单创建',
    '订单修改',
    '订单修改(审批)',
    '订单删除',
    '订单删除(审批)',
)

_TRUTHY = frozenset({'1', 'true', 'yes', 'on'})


def is_enabled() -> bool:
    """env 开关 ``INVENTORY_RECONCILE_ENABLED``：缺省 / 空值 = 关闭。

    键名必须以**字面量**传给 os.getenv：scripts/ops/check_env_drift.py:73-79 的
    CODE_REFS 正则只识别字面量键，经常量间接传入会让该键对门禁不可见
    （模板漂移检查形同虚设）。模板登记见 .env.example。
    """
    return os.getenv('INVENTORY_RECONCILE_ENABLED', '').strip().lower() in _TRUTHY


def classify_diff(diff: int) -> str:
    """把 ``diff`` 归类为 matched / positive / negative（纯函数，便于单测）。"""
    if diff > 0:
        return STATUS_POSITIVE
    if diff < 0:
        return STATUS_NEGATIVE
    return STATUS_MATCHED


def build_reconcile_statement() -> Select:
    """构造对账查询：``inventory_log`` 按产品聚合后 LEFT JOIN ``product``。

    一次 GROUP BY 拿到全部产品（含无流水产品，SUM 为空时 coalesce 为 0），
    避免逐产品查流水 —— 单条集合式查询，无 N+1。

    join 条件里排除 :data:`DEMAND_ONLY_CHANGE_TYPES`（订单需求类流水）：
    ``change_type IS NULL`` 的历史行必须仍计入——``NULL NOT IN (...)`` 结果是
    NULL（既非真也非假），只写 ``NOT IN`` 会把这些行静默漏掉，所以显式 OR 一支。
    """
    log_sum = func.coalesce(func.sum(InventoryLog.change_quantity), 0).label('log_sum')
    counts_toward_stock = or_(
        InventoryLog.change_type.is_(None),
        ~InventoryLog.change_type.in_(DEMAND_ONLY_CHANGE_TYPES),
    )
    return (
        select(
            Product.id,
            Product.name,
            Product.initial_stock,
            Product.current_stock,
            log_sum,
        )
        .select_from(Product)
        .outerjoin(
            InventoryLog,
            and_(InventoryLog.product_id == Product.id, counts_toward_stock),
        )
        .group_by(Product.id, Product.name, Product.initial_stock, Product.current_stock)
        .order_by(Product.id)
    )


async def reconcile_inventory(db: AsyncSession, *, diff_limit: int = DEFAULT_DIFF_LIMIT) -> dict[str, Any]:
    """只读对账一次：返回差异报告；不写任何表、不 commit。

    调用方（``tasks/inventory_reconcile_task.py``）只读会话即可，无需事务边界。
    """
    rows = (await db.execute(build_reconcile_statement())).all()
    report = summarize_rows(rows, diff_limit=diff_limit)
    report['checked_at'] = datetime.now(UTC).isoformat()
    return report


def summarize_rows(rows: Iterable[Sequence[Any]], *, diff_limit: int = DEFAULT_DIFF_LIMIT) -> dict[str, Any]:
    """把聚合行折叠成报告（纯函数：可直接喂构造数据做三分类用例）。

    行序约定：``(product_id, name, initial_stock, current_stock, log_sum)``。
    差异明细按 ``|diff|`` 降序（同值按 product_id 升序）便于人工先看大漂移。
    """
    matched = 0
    positive = 0
    negative = 0
    net_diff = 0
    abs_diff_total = 0
    diffs: list[dict[str, Any]] = []
    for product_id, name, initial_stock, current_stock, log_sum in rows:
        expected = int(log_sum or 0)
        diff = int(current_stock or 0) - expected
        net_diff += diff
        abs_diff_total += abs(diff)
        status = classify_diff(diff)
        if status == STATUS_MATCHED:
            matched += 1
            continue
        if status == STATUS_POSITIVE:
            positive += 1
        else:
            negative += 1
        diffs.append(
            {
                'product_id': int(product_id),
                'name': name,
                'initial_stock': int(initial_stock or 0),
                'current_stock': int(current_stock or 0),
                'log_sum': expected,
                'diff': diff,
                'status': status,
            }
        )
    diffs.sort(key=lambda item: (-abs(item['diff']), item['product_id']))
    return {
        'checked_products': matched + positive + negative,
        'matched': matched,
        'diff_count': positive + negative,
        'positive_count': positive,
        'negative_count': negative,
        'net_diff': net_diff,
        'abs_diff_total': abs_diff_total,
        'diff_limit': diff_limit,
        'truncated': len(diffs) > diff_limit,
        'diffs': diffs[:diff_limit],
    }
