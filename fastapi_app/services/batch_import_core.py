"""
批量 Excel 导入核心框架层

从 batch_import_service.py 拆出的通用导入框架 + 各 from_data 导入函数。
依赖 batch_import_parser 中的解析函数（parse_date_value、validate_customer_name）。
"""
import logging
from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.services.batch_import_dedup import dedupe_by_keys
from fastapi_app.services.batch_import_parser import parse_date_value, validate_customer_name
from fastapi_app.services.inventory_service import calculate_available_shipment_quantity
from fastapi_app.services.numbering import (
    generate_order_number,
    generate_stockin_number,
    generate_stockout_number,
)
from fastapi_app.services.order_deduction_service import process_order_deduction
from fastapi_app.shared.stock_concurrency import check_stock_available, get_product_for_update
from fastapi_app.shared_models import (
    Customer,
    InventoryLog,
    Order,
    Product,
    StockIn,
    StockOut,
)
from fastapi_app.shared_models.order import ORDER_STATUS_PENDING_STOCK

logger = logging.getLogger(__name__)


# ==================== 显式依赖包（DIP） ====================

@dataclass(frozen=True)
class ImportDeps:
    """批量导入核心依赖的显式打包。

    将模块级静态 import 的其他服务函数收敛为可注入依赖，
    调用方/测试可传入替换实现，消除跨服务静态强耦合。
    默认使用 default_import_deps() 解析的模块级实现，完全向后兼容。
    """

    generate_order_number: Callable = generate_order_number
    generate_stockin_number: Callable = generate_stockin_number
    generate_stockout_number: Callable = generate_stockout_number
    process_order_deduction: Callable = process_order_deduction
    calculate_available_shipment_quantity: Callable = calculate_available_shipment_quantity
    get_product_for_update: Callable = get_product_for_update


def default_import_deps() -> ImportDeps:
    """返回默认依赖包（模块级单例函数）。"""
    return ImportDeps()


@dataclass(frozen=True)
class DedupeSpec:
    """导入前的内存去重规格（ITER-2 决策 1：去重在应用层，不靠 DB 唯一约束）。

    传给 :func:`_import_data_generic` 后，行处理**之前**先做一遍内存去重：
    批内重复、与库中已有数据重复的行会被剔除並生成人类可读的错误消息，
    而不是静默跳过、也不是等到 ``executemany`` 时整批撞唯一约束失败。

    Attributes:
        key_fn: 从一行提取唯一键；返回 ``None`` 表示该行无从判定唯一性（一律保留）。
            需要大小写不敏感时用 ``batch_import_dedup.composite_key``。
        existing_keys: 库中已有数据的键集合。也可留空并改用 ``existing_keys_key``。
        existing_keys_key: ``pre_load`` 返回的 context 中的键名，用于取出库中已有的键集合。
            之所以需要它：``pre_load`` 查库发生在 ``_import_data_generic`` 内部，
            本规格作为入参传入时那些键还不存在，只能延迟到 context 就绪后再取。
        label: 错误消息里对这把键的称呼，如 ``'产品名称'``。
        message_limit: 最多回显多少条去重消息，超出部分汇总为一条。
            防止一个几千行的文件刷出上千条消息盖住真正的问题。
    """

    key_fn: Callable[[dict], Hashable | None]
    # 与 dedupe_by_keys 的参数类型保持一致（Iterable 而非 Container：
    # 下游要 `set(existing_keys)`，Container 不保证可迭代）。
    existing_keys: Iterable[Hashable] = ()
    existing_keys_key: str | None = None
    label: str = '唯一键'
    message_limit: int | None = 50


# ==================== 综合导入子函数 ====================

async def _pre_load_product_map(db: AsyncSession) -> dict:
    """预加载产品字典（按名称小写与条码双重索引）。

    订单导入与备货导入共用此预加载逻辑，避免重复实现。
    """
    result = await db.execute(select(Product))
    all_products = result.scalars().all()
    product_map = {p.name.lower().strip(): p for p in all_products}
    product_map.update({p.barcode: p for p in all_products if p.barcode})
    return {'product_map': product_map}


async def _pre_load_customer_names(db: AsyncSession) -> set:
    """一次性加载客户主数据中的有效名称（去首尾空白、大小写敏感）。

    订单/备货的 customer 是无外键的名字快照，导入时若不校验会在库里留下
    永远关联不到客户的孤儿单据（2026-08-10 曾因此产生 19 张孤儿订单）。
    """
    result = await db.execute(select(Customer.name))
    return {name.strip() for (name,) in result.all() if name and name.strip()}


async def _pre_load_order_context(db: AsyncSession) -> dict:
    """订单/备货导入的复合预加载：产品字典 + 有效客户名集合。"""
    ctx = await _pre_load_product_map(db)
    ctx['customer_names'] = await _pre_load_customer_names(db)
    return ctx


async def _resolve_row_identity(context: dict, idx: int, customer: str, product_name: str,
                                debug_messages: list, *, silent_missing: bool = False,
                                label: str = '') -> tuple[Product | None, str | None]:
    """校验客户并解析产品，返回 ``(product, customer)``；校验失败返回 ``(None, None)``。

    订单导入与备货导入的核心校验一致（客户名称格式校验 + 必须存在于客户主数据
    + 产品按小写名/原名双查），差别仅在失败时是否记 debug 消息。抽出以免两处各写一遍。

    客户必须在客户主数据中：``customer`` 是无外键的名字快照，不校验会在库里留下
    永远关联不到客户的孤儿单据（2026-08-10 曾因此产生 19 张孤儿订单）。

    Args:
        silent_missing: 为 True 时，客户格式非法/产品不存在**不记 debug 消息**
            （备货导入的既有行为）；客户不在主数据始终记消息（这是新增的防孤儿校验）。
        label: debug 消息前缀，如 ``'订单'``。
    """
    is_valid, error_msg = validate_customer_name(customer)
    if not is_valid:
        if not silent_missing:
            debug_messages.append(f"行{idx}: {label}客户验证失败 - {error_msg}")
        return None, None

    if customer not in context['customer_names']:
        debug_messages.append(f"行{idx}: 客户'{customer}'不存在于客户主数据，请先在客户管理中创建")
        return None, None

    product_map = context['product_map']
    product = product_map.get(product_name.lower().strip())
    product = product or product_map.get(product_name)
    if not product:
        if not silent_missing:
            debug_messages.append(f"行{idx}: 产品不存在 - {product_name}")
        return None, None

    return product, customer


def _parse_positive_quantity(quantity, idx: int, *, label: str,
                             product_name: str, customer: str) -> int | None:
    """把数量转成正整数；无法解析或非正数返回 ``None``（调用方跳过该行）。"""
    try:
        qty = int(quantity)
    except (ValueError, TypeError):
        logger.warning("%s导入：quantity 解析失败，跳过该行 (product=%s, customer=%s, value=%r)",
                       label, product_name, customer, quantity)
        return None
    return qty if qty > 0 else None


async def _import_data_generic(
    db: AsyncSession,
    data_list: list,
    row_handler,
    pre_load=None,
    use_savepoint: bool = True,
    has_debug_messages: bool = True,
    label: str = "导入",
    dedupe: DedupeSpec | None = None,
):
    """
    通用导入数据框架

    Args:
        db: 数据库会话
        data_list: 数据行列表
        row_handler: 异步回调 async (db, row_data, idx, context, debug_messages) -> bool
            返回 True 表示该行成功导入，False 表示跳过
        pre_load: 异步回调 async (db) -> dict，预加载数据
        use_savepoint: 是否使用 savepoint 包裹每行处理
        has_debug_messages: 是否收集调试消息
        label: 导入类型标签，用于日志和完成消息
        dedupe: 可选的内存去重规格（见 :class:`DedupeSpec`）。不传则行为完全不变。
    """
    count = 0
    debug_messages: list[str] | None = [] if has_debug_messages else None

    context = await pre_load(db) if pre_load else {}

    if dedupe is not None:
        # 去重先于行处理：重复行不进循环，也就不会撞唯一约束。
        # kept 保留原始行号，使后续错误消息与 Excel 里看到的行号一致。
        existing_keys = dedupe.existing_keys
        if dedupe.existing_keys_key is not None:
            existing_keys = context.get(dedupe.existing_keys_key) or ()
        deduped = dedupe_by_keys(
            data_list,
            dedupe.key_fn,
            existing_keys=existing_keys,
            label=dedupe.label,
        )
        rows_to_process = deduped.kept
        if debug_messages is not None:
            debug_messages.extend(deduped.error_messages(limit=dedupe.message_limit))
        if deduped.removed_count:
            logger.info(
                "%s：去重跳过 %d 行（输入 %d 行）",
                label, deduped.removed_count, deduped.total_count,
            )
    else:
        rows_to_process = list(enumerate(data_list, start=2))

    for idx, row_data in rows_to_process:
        try:
            if use_savepoint:
                async with db.begin_nested():
                    if await row_handler(db, row_data, idx, context, debug_messages):
                        count += 1
            else:
                if await row_handler(db, row_data, idx, context, debug_messages):
                    count += 1
        except (ValueError, TypeError, SQLAlchemyError) as e:
            if debug_messages is not None:
                debug_messages.append(f"行{idx}: 异常 - {e!s}")
            logger.error(f"{label} - 行{idx}: 异常 - {e!s}", exc_info=True)
            continue

    await db.flush()

    # 完成消息只进日志，不再 append 进 debug_messages：
    # debug_messages 的语义是「行级消息」，调用方（_process_comprehensive_sheet）
    # 会把它整体并进 results.errors 展示给用户，混入完成消息会污染错误列表。
    logger.info("%s完成: 共导入 %d 条", label, count)

    if has_debug_messages:
        return count, debug_messages
    return count


def _product_dedupe_key(row: dict) -> str | None:
    """产品导入的唯一键：产品名称（去首尾空白 + casefold）。

    归一化必须与 ``Product.name`` 既有匹配口径一致（大小写不敏感、去空白），
    否则「Acme」与「acme 」会被当成两个产品 —— 正是要去防的那种重复。
    返回 ``None`` 表示该行没有产品名，无从判定唯一性，一律保留。
    """
    name = row.get('产品名称') or row.get('产品名') or row.get('名称')
    if not name:
        return None
    return str(name).strip().casefold()


async def import_products_from_data(db: AsyncSession, data_list: list) -> tuple[int, list[str]]:
    """从数据列表导入产品。

    Returns:
        ``(成功导入条数, 错误消息列表)``。重复行（批内重复 / 与库中已有重复）
        在进入行处理**之前**被剔除，并为每行生成一条可读消息，
        不再像以前那样静默 ``return False``。
    """
    async def _pre_load(db):
        existing_result = await db.execute(select(func.lower(Product.name)))
        existing_names = {row[0].casefold() for row in existing_result.all() if row[0]}
        return {'existing_names': existing_names}

    async def _row_handler(db, row_data, idx, context, debug_messages):
        existing_names = context['existing_names']
        name = row_data.get('产品名称') or row_data.get('产品名') or row_data.get('名称')
        barcode = row_data.get('69码') or row_data.get('条码') or row_data.get('条形码')
        price = row_data.get('产品价格') or row_data.get('价格')
        initial_stock = row_data.get('初始库存') or row_data.get('库存') or 0

        if not name:
            return False

        name = str(name).strip()

        # 与库中已有产品的重复已由 dedupe 前置剔除；此处保留为防御性检查
        # （历史行为：直接 return False，不产生任何消息）。
        if name.lower() in existing_names:
            return False

        try:
            stock = int(initial_stock) if initial_stock else 0
        except ValueError:
            logger.warning("产品导入：initial_stock 解析失败，使用默认值 0 (name=%s, value=%r)", name, initial_stock)
            stock = 0

        try:
            # Decimal(str(...)) 直转：避免 float 二进制近似值进入 Numeric 列
            from decimal import Decimal, InvalidOperation

            price_val = Decimal(str(price)) if price else Decimal('0')
        except (ValueError, TypeError, InvalidOperation):
            logger.warning("产品导入：price 解析失败，使用默认值 0 (name=%s, value=%r)", name, price)
            price_val = Decimal('0')

        product = Product(
            name=name,
            barcode=str(barcode).strip() if barcode else '',
            price=price_val,
            initial_stock=stock,
            current_stock=stock
        )
        db.add(product)
        return True

    return await _import_data_generic(
        db, data_list, _row_handler,
        pre_load=_pre_load,
        use_savepoint=False,
        has_debug_messages=True,
        label="产品导入",
        dedupe=DedupeSpec(
            key_fn=_product_dedupe_key,
            existing_keys_key='existing_names',
            label='产品名称',
        ),
    )


async def import_orders_from_data(db: AsyncSession, data_list: list, *, deps: ImportDeps | None = None) -> tuple[int, list]:
    """从数据列表导入订单

    Args:
        deps: 可注入的依赖包（默认解析模块级实现）。
    """
    deps = deps or default_import_deps()

    async def _row_handler(db, row_data, idx, context, debug_messages):
        customer = row_data.get('客户名称') or row_data.get('客户')
        product_name = row_data.get('产品名称') or row_data.get('产品')
        quantity = row_data.get('数量') or row_data.get('订单数量')
        note = row_data.get('备注') or ''
        deduct_flag = row_data.get('抵扣备货') or row_data.get('是否抵扣备货') or row_data.get('抵扣')

        if not customer or not product_name or not quantity:
            return False

        customer = str(customer).strip()
        product_name = str(product_name).strip()

        product, customer = await _resolve_row_identity(
            context, idx, customer, product_name, debug_messages)
        # _resolve_row_identity 失败时返回 (None, None)，成功时 customer 必为已校验的非空 str；
        # 显式判 None 只是把该不变式写出来（mypy 无法跨元组元素收窄），运行期行为不变。
        if product is None or customer is None:
            return False
        product_id = product.id

        qty = _parse_positive_quantity(
            quantity, idx, label='订单', product_name=product_name, customer=customer)
        if qty is None:
            return False

        order_no = await deps.generate_order_number(db)
        order = Order(
            order_no=order_no,
            customer=customer,
            order_date=datetime.now(UTC),  # aware UTC：order_date 列为 timestamptz
            product_id=product_id,
            quantity=qty,
            note=str(note).strip() if note else '',
            status=ORDER_STATUS_PENDING_STOCK
        )
        db.add(order)
        await db.flush()

        # 使用悲观锁更新产品库存，防止并发修改
        locked_product = await deps.get_product_for_update(db, product_id)
        locked_product.current_stock += qty

        log = InventoryLog(
            product_id=product_id,
            change_type='订单',
            change_quantity=qty,
            related_id=order_no,
            note='综合导入订单：' + order_no
        )
        db.add(log)

        # 处理抵扣备货逻辑
        if deduct_flag:
            try:
                deduct_flag_str = str(deduct_flag).strip()
                deduct_value = 0
                if deduct_flag_str.isdigit():
                    deduct_value = int(deduct_flag_str)
                elif deduct_flag_str.lower() in ['是', 'yes']:
                    deduct_value = 1

                if deduct_value > 0:
                    await deps.process_order_deduction(db, order, product_id, deduct_value, deduct_stock=True, product=product)
            except (ValueError, TypeError, SQLAlchemyError) as e:
                logger.error(f"订单导入 - 行{idx}: 抵扣处理异常: {e}", exc_info=True)

        return True

    count, debug_messages = await _import_data_generic(
        db, data_list, _row_handler,
        pre_load=_pre_load_order_context,
        use_savepoint=True,
        has_debug_messages=True,
        label="订单导入",
    )
    debug_messages.insert(0, f"开始处理订单数据，共{len(data_list)}行")
    return count, debug_messages


async def import_stockins_from_data(db: AsyncSession, data_list: list, *, deps: ImportDeps | None = None) -> tuple[int, list]:
    """从数据列表导入备货

    Args:
        deps: 可注入的依赖包（默认解析模块级实现）。
    """
    deps = deps or default_import_deps()

    async def _row_handler(db, row_data, idx, context, debug_messages):
        customer = row_data.get('客户名称') or row_data.get('客户')
        product_name = row_data.get('产品名称') or row_data.get('产品')
        quantity = row_data.get('数量') or row_data.get('备货数量')
        stockin_date_val = row_data.get('时间') or row_data.get('备货时间')
        note = row_data.get('备注') or ''

        if not customer or not product_name or not quantity:
            return False

        customer = str(customer).strip()
        product_name = str(product_name).strip()

        product, customer = await _resolve_row_identity(
            context, idx, customer, product_name, debug_messages, silent_missing=True)
        # 同 import_orders_from_data：失败即 (None, None)，成功时 customer 必为非空 str。
        if product is None or customer is None:
            return False
        product_id = product.id

        qty = _parse_positive_quantity(
            quantity, idx, label='备货', product_name=product_name, customer=customer)
        if qty is None:
            return False

        stockin_date = parse_date_value(stockin_date_val) or datetime.now(UTC)  # aware UTC：stockin_date 列为 timestamptz
        stockin_no = await deps.generate_stockin_number(db)
        stockin = StockIn(
            stockin_no=stockin_no,
            stockin_date=stockin_date,
            customer=customer,
            product_id=product_id,
            quantity=qty,
            note=str(note).strip() if note else ''
        )
        db.add(stockin)

        # 使用悲观锁更新产品库存，防止并发修改
        locked_product = await deps.get_product_for_update(db, product_id)
        locked_product.current_stock += qty

        log = InventoryLog(
            product_id=product_id,
            change_type='备货',
            change_quantity=qty,
            related_id=stockin_no,
            note='综合导入备货：' + stockin_no
        )
        db.add(log)

        return True

    return await _import_data_generic(
        db, data_list, _row_handler,
        pre_load=_pre_load_order_context,
        use_savepoint=True,
        has_debug_messages=True,
        label="备货导入",
    )


async def import_stockouts_from_data(db: AsyncSession, data_list: list, *, deps: ImportDeps | None = None) -> tuple[int, list]:
    """从数据列表导入出货

    Args:
        deps: 可注入的依赖包（默认解析模块级实现）。
    """
    deps = deps or default_import_deps()

    async def _row_handler(db, row_data, idx, context, debug_messages):
        product_identifier = row_data.get('产品名称') or row_data.get('产品') or row_data.get('69码') or row_data.get('条码')
        quantity = row_data.get('数量') or row_data.get('出货数量')
        customer = row_data.get('客户名称') or row_data.get('客户')
        stockout_date_val = row_data.get('时间') or row_data.get('出货时间')
        note = row_data.get('备注') or ''

        if not product_identifier or not quantity:
            return False

        product_identifier = str(product_identifier).strip()
        customer = str(customer).strip() if customer else ''

        if not customer:
            return False

        # 查找产品
        result = await db.execute(
            select(Product).where(
                (Product.name == product_identifier) | (Product.barcode == product_identifier)
            )
        )
        product = result.scalar_one_or_none()
        if not product:
            return False

        try:
            qty = int(quantity)
            if qty <= 0:
                return False
        except ValueError:
            logger.warning("出货导入：quantity 解析失败，跳过该行 (product=%s, customer=%s, value=%r)", product_identifier, customer, quantity)
            return False

        # 负库存判定统一走统一入口（P1-2b）；策略拒绝时按原行为跳过该行
        if check_stock_available(product.current_stock, -qty) is not None:
            return False

        shipment_info = await deps.calculate_available_shipment_quantity(
            db, product.id, customer,
        )
        if shipment_info['available_quantity'] <= 0:
            return False

        if qty > shipment_info['available_quantity']:
            return False

        stockout_date = parse_date_value(stockout_date_val) or datetime.now(UTC)  # aware UTC：stockout_date 列为 timestamptz

        remaining_qty = qty
        for order_detail in shipment_info['orders']:
            if remaining_qty <= 0:
                break
            if order_detail['available'] > 0:
                ship_qty = min(remaining_qty, order_detail['available'])
                stockout_no = await deps.generate_stockout_number(db)
                stockout = StockOut(
                    stockout_no=stockout_no,
                    stockout_date=stockout_date,
                    product_id=product.id,
                    quantity=ship_qty,
                    customer=customer,
                    order_id=order_detail['order_id'],
                    note=str(note).strip() if note else ''
                )
                db.add(stockout)
                remaining_qty -= ship_qty

        # 使用悲观锁更新产品库存，防止并发修改
        locked_product = await deps.get_product_for_update(db, product.id)
        locked_product.current_stock -= qty

        log = InventoryLog(
            product_id=product.id,
            change_type='出库',
            change_quantity=-qty,
            related_id='',
            note=f'综合导入出货：客户{customer}，数量{qty}'
        )
        db.add(log)

        return True

    return await _import_data_generic(
        db, data_list, _row_handler,
        pre_load=None,
        use_savepoint=True,
        has_debug_messages=True,
        label="出货导入",
    )
