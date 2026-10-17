"""批量导入异步任务

Excel 批量导入耗时操作由 ARQ Worker 执行。行循环使用异步会话
（numbering_counter 原子取号，spec 2026-09-29 订单号统一 §4.2）。

P1-7：ARQ 的 ``max_tries=3`` 会**重放**失败任务（``ctx["job_try"]`` 递增、``job_id`` 不变），
故入口按 ``job_id + 行业务主键`` 做重放幂等（见 ``core/arq_app.py`` 的 ``job_idempotency``），
行循环改为经 ``CommitBatcher`` 每批提交一次。
"""
import contextlib
import hashlib
import os
import tempfile

from sqlalchemy import or_
from sqlalchemy import select as sa_select

from fastapi_app.core.logger import logger
from fastapi_app.shared_models import Product
from fastapi_app.shared_models.order import ORDER_STATUS_PENDING_STOCK

# 每批提交条数。值保持 P1-7 前的 50：fastapi_app/tests/test_batch_tasks_semantics.py 的
# test_fifty_row_batch_commit_semantics 用 110 行断言 ``session.commits >= 3`` 锁定了它；
# 若要改成 core/arq_app.py 的 DEFAULT_COMMIT_BATCH_SIZE(200)，必须同步改该用例。
BATCH_COMMIT_SIZE = 50

ALLOWED_UPLOAD_DIRS = [
    tempfile.gettempdir(),
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'static', 'uploads'),
]


def _is_allowed_upload_path(file_path: str) -> bool:
    """校验上传文件路径是否位于允许的目录内。

    两侧均取 ``realpath``：Windows 下 ``tempfile.gettempdir()`` 可能返回 8.3 短名
    （如 ``C:\\Users\\ADMINI~1\\...``），而 ``realpath(file_path)`` 会展开为长名，
    不归一会导致本应命中的临时目录被判为不匹配。跨盘符时 ``os.path.commonpath``
    抛 ``ValueError``，按"不在该目录内"处理并继续检查下一个候选目录。
    """
    real_path = os.path.realpath(file_path)
    for d in ALLOWED_UPLOAD_DIRS:
        if not os.path.exists(d):
            continue
        real_dir = os.path.realpath(d)
        try:
            if os.path.commonpath([real_path, real_dir]) == real_dir:
                return True
        except ValueError:
            # 跨盘符：commonpath 拒绝混合 drive，视为不在该目录内
            continue
    return False


async def _parse_rows_async(file_path: str) -> tuple[bool, list, str]:
    """解析 Excel（阻塞解析仍在 executor 里跑，不阻塞 worker 事件循环）。

    这里刻意**兜底捕获宽异常**（``Exception``），以保留解析层原有的"畸形文件返回
    错误结果、而非抛出"契约：``parse_excel_file_async`` 内部只捕获
    ``(ValueError, TypeError, OSError)``，而 polars / zipfile 对畸形 xlsx 会抛
    ``zipfile.BadZipFile`` 等**不在该元组内**的异常。若任其逃逸，
    ``_run_batch_import_async`` 的窄 ``except (ValueError, TypeError, OSError)``
    捕获不到 → ``delete_file`` 保持 True → **用户上传的文件被删除**，且 ARQ 重试
    时文件已不存在。旧解析器（``utils/batch_upload_utils.parse_excel_file``）捕获裸
    ``Exception`` 并返回 ``(False, [], msg)``，此处逐字还原该语义。
    （``batch_import_parser`` 自身的窄捕获契约保持不变。）
    """
    from fastapi_app.services.batch_import_parser import parse_excel_file_async

    try:
        return await parse_excel_file_async(file_path)
    except Exception as e:  # broad-except: 还原旧解析器契约——畸形文件返回错误结果而非抛出
        return False, [], str(e)


async def _open_import_session():
    """开启异步导入会话（延迟导入，避免 import 期绑定引擎）。"""
    from fastapi_app.core.database import require_async_session_local

    return require_async_session_local()()


async def _resolve_product_locked(db, product_identifier: str) -> Product | None:
    """按名称/条码查找产品并加行锁，未找到返回 None。"""
    result = await db.execute(
        sa_select(Product).where(
            or_(Product.name == product_identifier, Product.barcode == product_identifier)
        ).with_for_update()
    )
    return result.scalar_one_or_none()


async def _resolve_row_product(db, row: dict) -> tuple[Product | None, str | None]:
    """解析行内产品标识并加行锁；返回 (product, 错误消息)。缺少必填字段/产品不存在返回错误消息。"""
    product_identifier = row.get('产品名称', row.get('产品编号', ''))
    customer = row.get('客户名称', '')
    quantity = row.get('数量', 0)
    if not all([product_identifier, customer, quantity]):
        return None, '缺少必填字段'
    # all() 只判真值，负数/零会被放过（负数 truthy）。数量语义上必须是正整数，
    # 与 batch_import_core._parse_positive_quantity（qty>0 else None）、
    # plan_tasks（quantity<=0 拒行）同口径 —— 2026-10-17 审计 F-BE-CORE-01。
    if not isinstance(quantity, (int, float)) or isinstance(quantity, bool) \
            or int(quantity) != quantity or int(quantity) <= 0:
        return None, f'数量无效：{quantity!r}（必须为正整数）'
    product = await _resolve_product_locked(db, product_identifier)
    if not product:
        return None, f"产品 '{product_identifier}' 不存在"
    return product, None


def _row_business_key(row: dict, row_no: int) -> str:
    """行的业务主键（P1-7 幂等集合的成员）：行号 + 行内容哈希。

    行号进键，使「同一文件里两行内容完全相同」也能各自被处理（那是
    ``services/batch_import_dedup.py`` 的批内去重语义，不在这里）；内容哈希保证同一文件
    在重放时（重新解析）产出同样的键，且不随列序/无关列变化。
    """
    fields = ('产品名称', '产品编号', '客户名称', '数量', '备注')
    payload = chr(31).join(str(row.get(name, '')) for name in fields)
    digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()[:32]
    return f'{row_no}:{digest}'


async def _import_rows(db, data_list: list, build_row, task_label: str, *, job_id: str,
                       batch_size: int, idempotency) -> dict:
    """行循环：重放幂等跳过 + 每 ``batch_size`` 条提交一次（P1-7）。

    幂等标记只在**提交成功之后**登记（``CommitBatcher`` 的 ``after_commit`` 钩子）：被回滚的
    批次不会被标成「已处理」——否则重放时那些行就真的丢了，这比重复写更糟。
    """
    from fastapi_app.core.arq_app import CommitBatcher

    imported_count = 0
    last_committed_count = 0
    skipped_idempotent = 0
    errors: list[dict] = []
    pending_marks: list[str] = []
    already_done = await idempotency.load() if idempotency is not None else set()

    async def _on_batch_committed() -> None:
        # 提交成功：把「本批处理过的业务主键」登记进幂等集合，并推进已提交计数。
        nonlocal last_committed_count
        last_committed_count = imported_count
        if idempotency is not None and pending_marks:
            await idempotency.mark(pending_marks)
        pending_marks.clear()

    batcher = CommitBatcher(db, batch_size=batch_size, after_commit=_on_batch_committed)
    for i, row in enumerate(data_list, start=2):
        mark = _row_business_key(row, i) if idempotency is not None else ''
        if mark and mark in already_done:
            skipped_idempotent += 1
            logger.info(f'批量导入{task_label}行{i}已在本 job 提交过，重放跳过')
            continue
        try:
            row_error = await build_row(db, row, i)
        except (ValueError, TypeError, OSError) as e:
            await db.rollback()
            # 保留已提交批次的计数，仅回滚当前未提交批次
            uncommitted_in_batch = imported_count - last_committed_count
            imported_count = last_committed_count
            pending_marks.clear()
            batcher.reset()
            errors.append({'row': i, 'error': str(e), 'skipped_uncommitted': uncommitted_in_batch})
            logger.error(f'批量导入{task_label}行{i}失败: {e}')
            continue
        if row_error:
            errors.append({'row': i, 'error': row_error})
            continue
        imported_count += 1
        if mark:
            pending_marks.append(mark)
        await batcher.tick()
    await batcher.flush()
    return {
        'success': True,
        'imported_count': imported_count,
        'errors': errors,
        'skipped_idempotent': skipped_idempotent,
        'task_id': job_id,
    }


async def _run_batch_import_async(file_path: str, job_id: str, task_label: str, build_row, *,
                                  batch_size: int = BATCH_COMMIT_SIZE, idempotency=None) -> dict:
    """订单/备货批量导入共享骨架（异步版）。

    语义与同步版逐字一致（行级失败 continue / ValueError/TypeError/OSError 回滚当前未提交批并计
    skipped_uncommitted / 抛出时保留文件供重试）；批提交粒度与重放幂等由 ``_import_rows`` 承担。

    Args:
        file_path: 已保存的临时文件路径。
        job_id: ARQ 任务 ID。
        task_label: 任务标签（日志用，如 '订单'/'备货'）。
        build_row: 单行处理协程 ``async def(db, row, i) -> str | None``。
        batch_size: 每批提交条数（默认 ``BATCH_COMMIT_SIZE``）。
        idempotency: 重放幂等闸门（``core/arq_app.py`` 的 ``JobIdempotency``）；None 不去重。

    Returns:
        dict: {success, imported_count, errors, skipped_idempotent, task_id}
    """
    if not _is_allowed_upload_path(file_path):
        logger.error(f'批量导入{task_label}任务拒绝非法文件路径: {file_path}')
        return {'success': False, 'error': '非法文件路径', 'imported_count': 0, 'task_id': job_id}
    delete_file = True
    try:
        success, data_list, error = await _parse_rows_async(file_path)
        if not success:
            return {'success': False, 'error': error, 'imported_count': 0, 'task_id': job_id}
        db = await _open_import_session()
        try:
            return await _import_rows(db, data_list, build_row, task_label, job_id=job_id,
                                      batch_size=batch_size, idempotency=idempotency)
        finally:
            await db.close()
    except (ValueError, TypeError, OSError) as exc:
        logger.error(f'批量导入{task_label}任务失败: {exc}', exc_info=True)
        # 保留文件以供 ARQ 重试（max_tries 控制重试上限）
        delete_file = False
        raise exc
    except Exception as exc:
        # 2026-10-17 审计 F-BE-CORE-02：非预期异常（SQLAlchemyError 死锁/断连、
        # assert 失败等）原先走 delete_file=True → finally 删掉用户源文件 →
        # ARQ 三次重试全部「文件不存在」。既然异常在向外抛（任务未成功），文件
        # 一律保留，让重试仍有输入可用。
        logger.error(f'批量导入{task_label}任务未预期异常（保留源文件供重试）: {exc}', exc_info=True)
        delete_file = False
        raise exc
    finally:
        if delete_file and file_path and os.path.exists(file_path):
            with contextlib.suppress(OSError):
                os.unlink(file_path)


async def batch_import_orders_task(ctx, file_path: str, original_filename: str, user_id: int):
    """异步批量导入订单

    Args:
        ctx: ARQ 上下文（含 job_id / job_try）
        file_path: 已保存的临时文件路径
        original_filename: 原始文件名
        user_id: 操作用户ID

    Returns:
        dict: 导入结果 {success, imported_count, errors, task_id}
    """
    job_id = ctx['job_id']

    async def _orders_row(db, row: dict, i: int) -> str | None:
        from datetime import UTC, datetime

        from fastapi_app.services.numbering import generate_order_number
        from fastapi_app.shared_models import InventoryLog, Order
        product, row_error = await _resolve_row_product(db, row)
        if row_error:
            return row_error
        # row_error 为 None ⇒ 产品必然存在
        assert product is not None  # noqa: S101
        order = Order(
            order_no=await generate_order_number(db),
            product_id=product.id, customer=row.get('客户名称', ''),
            quantity=int(row.get('数量', 0)),
            order_date=datetime.now(UTC),  # aware UTC：order_date 为 timestamptz
            status=ORDER_STATUS_PENDING_STOCK, note=row.get('备注', ''))
        db.add(order)
        await db.flush()
        log = InventoryLog(product_id=product.id, change_type='订单创建',
                           change_quantity=int(row.get('数量', 0)),
                           change_date=datetime.now(UTC), customer=row.get('客户名称', ''),
                           related_id=str(order.id), note=f'批量导入订单 {order.order_no}')
        db.add(log)
        return None

    from fastapi_app.core.arq_app import IDEMPOTENCY_NAMESPACE_BATCH_IMPORT, job_idempotency

    idempotency = job_idempotency(ctx, namespace=IDEMPOTENCY_NAMESPACE_BATCH_IMPORT)
    return await _run_batch_import_async(file_path, job_id, '订单', _orders_row, idempotency=idempotency)


async def batch_import_stockins_task(ctx, file_path: str, original_filename: str, user_id: int):
    """异步批量导入备货"""
    job_id = ctx['job_id']

    async def _stockins_row(db, row: dict, i: int) -> str | None:
        from datetime import UTC, datetime

        from fastapi_app.services.numbering import generate_stockin_number
        from fastapi_app.shared_models import InventoryLog, StockIn
        product, row_error = await _resolve_row_product(db, row)
        if row_error:
            return row_error
        # row_error 为 None ⇒ 产品必然存在
        assert product is not None  # noqa: S101
        quantity = int(row.get('数量', 0))
        stockin = StockIn(
            stockin_no=await generate_stockin_number(db),
            product_id=product.id, customer=row.get('客户名称', ''),
            quantity=quantity, stockin_date=datetime.now(UTC),
            note=row.get('备注', ''))
        db.add(stockin)
        await db.flush()
        # 必须走统一库存写入口：直写 `product.current_stock += quantity` **不递增 version**，
        # 与并发走乐观锁的写路径（如 product_service.update_product）交错时会丢失更新
        # （对方 WHERE version=旧值 命中、覆盖本批数量）。与 stock_in_service 被修的原因相同。
        # 注意：本目录 fastapi_app/tasks 原先**不在**仓库级残留扫描白名单内
        # （test_stock_negative_policy_repo_wide.py 的 SERVICE_AND_SHARED_ROOTS），
        # 故此处直写从未被门禁覆盖 —— 已把 tasks 纳入扫描。
        from fastapi_app.shared.stock_concurrency import apply_stock_delta_locked
        await apply_stock_delta_locked(db, product, quantity)
        log = InventoryLog(product_id=product.id, change_type='备货入库',
                           change_quantity=quantity, change_date=datetime.now(UTC),
                           customer=row.get('客户名称', ''), related_id=str(stockin.id),
                           note=f'批量导入备货 {stockin.stockin_no}')
        db.add(log)
        return None

    from fastapi_app.core.arq_app import IDEMPOTENCY_NAMESPACE_BATCH_IMPORT, job_idempotency

    idempotency = job_idempotency(ctx, namespace=IDEMPOTENCY_NAMESPACE_BATCH_IMPORT)
    return await _run_batch_import_async(file_path, job_id, '备货', _stockins_row, idempotency=idempotency)
