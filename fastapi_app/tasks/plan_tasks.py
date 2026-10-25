"""
采购计划相关异步任务

- 出货数据每日同步（ARQ cron 定时任务）
- 批量计划导入（>500行时异步处理）

使用 SyncSessionLocal + shared_models，同步 DB 操作通过 asyncio.to_thread 运行。
"""
import asyncio
import contextlib
import os
from datetime import date, timedelta

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from fastapi_app.core.database import get_sync_engine
from fastapi_app.core.logger import logger
from fastapi_app.services.plan_utils import normalize_plan_date

_SyncSession = sessionmaker(
    autocommit=False, autoflush=False, bind=get_sync_engine()
)


def _sync_target_dates(today: date, lookback_days: int = 3) -> list[date]:
    """从业务昨日开始回看 N 天；窗口内每天幂等 upsert，自然补上漏跑。"""
    return [today - timedelta(days=i) for i in range(1, lookback_days + 1)]


def _sync_one_date(session, target_date: date, customer_id_map: dict[str, int]) -> int:
    """同步单日出货数据（按 shipment_no 幂等 upsert），返回写入/更新条数。"""
    from sqlalchemy import text

    rows = session.execute(text("\n                SELECT so.id, so.stockout_no, so.customer, so.product_id,\n                       so.quantity, so.returned_quantity, DATE(so.stockout_date) as stockout_date,\n                       p.name as product_name\n                FROM stock_out so\n                JOIN product p ON so.product_id = p.id\n                WHERE DATE(so.stockout_date) = :target_date\n                  AND so.customer IS NOT NULL AND so.customer != ''\n            "), {'target_date': target_date}).fetchall()
    synced = 0
    for row in rows:
        customer_id = customer_id_map.get(row.customer)
        if not customer_id:
            continue
        existing = session.execute(text('SELECT id FROM shipment_records WHERE shipment_no = :no'), {'no': row.stockout_no}).fetchone()
        if existing:
            session.execute(text('\n                        UPDATE shipment_records\n                        SET quantity = :qty, synced_at = NOW()\n                        WHERE shipment_no = :no\n                    '), {'qty': row.quantity - row.returned_quantity, 'no': row.stockout_no})
        else:
            # 走 ORM 而非原生 SQL：created_at/synced_at 只有 Python 侧 default
            # （无 server_default），原生 INSERT 列清单漏列即 NotNullViolation——
            # 2026-10-23 起生产每日同步因此断流 3 天（2026-10-25 上线前审计 H-1）。
            from fastapi_app.shared_models.purchase_plan import ShipmentRecord
            session.add(ShipmentRecord(
                shipment_no=row.stockout_no,
                customer_id=customer_id,
                customer_name=row.customer,
                product_id=row.product_id,
                product_name=row.product_name,
                quantity=row.quantity - row.returned_quantity,
                shipment_date=row.stockout_date,
                source_id=row.id,
            ))
        synced += 1
    return synced


async def sync_shipment_records_task(ctx):
    """
    每日凌晨同步出货数据

    从 stock_out 表同步业务昨日（并回看 3 天）的数据到 shipment_records 表。
    用业务时区而非 UTC 日界：ARQ cron 按系统时区（CST）在 01:00 触发，
    UTC 日期此时是前一日，`now(UTC).date()-1` 会同步成「前天」。
    """
    def _sync_impl():
        try:
            from sqlalchemy import text

            from fastapi_app.core.business_time import business_today
            session = _SyncSession()
            try:
                target_dates = _sync_target_dates(business_today())
                customers = session.execute(text('SELECT id, name FROM customer')).fetchall()
                customer_id_map = {c.name: c.id for c in customers}
                synced_count = 0
                for target_date in target_dates:
                    synced_count += _sync_one_date(session, target_date, customer_id_map)
                    session.commit()
                logger.info(f'出货记录同步完成：{target_dates[-1]}..{target_dates[0]}，{synced_count}条')
                return {'success': True, 'synced_count': synced_count, 'target_dates': [d.isoformat() for d in target_dates]}
            finally:
                session.close()
        except (ValueError, TypeError, OSError) as exc:
            logger.error(f'出货同步任务失败: {exc}', exc_info=True)
            raise exc

    return await asyncio.to_thread(_sync_impl)


def _batch_id_for_job(job_id: str) -> str:
    """同一 ARQ job 在重试间 job_id 不变，用它派生 batch_id 才能幂等重放。

    P1（2026-10-24）：用完整 job_id，不再截前 8 位。8 位十六进制只有 32 bit，
    约 7.7 万个导入任务后碰撞概率达 50%；一旦命中，新任务开跑时的
    `DELETE ... WHERE upload_batch_id='job-xxxxxxxx'` 会删掉另一次（可能正在确认中的）
    导入的暂存行，用户侧表现为「刚上传的计划凭空消失」。
    upload_batch_id 是字符串列，改长度不影响存量数据。
    """
    return f"job-{job_id}"


def _clear_batch_rows(session, batch_id: str) -> None:
    """幂等替换：重放前清掉同一 batch 的旧行，避免重复插入。"""
    from sqlalchemy import delete

    from fastapi_app.shared_models import StagingPurchasePlan

    session.execute(
        delete(StagingPurchasePlan).where(StagingPurchasePlan.upload_batch_id == batch_id)
    )
    session.commit()


async def batch_import_plans_task(ctx, file_path: str, original_filename: str, user_id: int):
    """
    大批量计划导入（>500行时由API层触发）

    输入：临时文件路径、原始文件名、用户ID
    处理：解析 Excel → 写入 staging → 返回 batch_id
    """
    job_id = ctx['job_id']
    return await asyncio.to_thread(_run_import_plans_impl, file_path, user_id, job_id)


def _run_import_plans_impl(file_path: str, user_id: int, job_id: str,
                           session_factory=None):
    # session_factory 仅测试注入；生产走模块级 _SyncSession
    # 复用 batch_tasks 里已修好的版本：候选目录与 file_path 两侧都取 realpath
    # （Windows 短名 8.3 不一致会误拒合法临时文件），且 commonpath 跨盘符
    # 抛的 ValueError 有兜底。此处原先是未同步的旧副本，且判断在 try 之外，
    # ValueError 会逃逸出 _sync_impl 让 ARQ 任务失败重放。
    from fastapi_app.tasks.batch_tasks import _is_allowed_upload_path
    if not _is_allowed_upload_path(file_path):
        logger.error(f'批量计划导入任务拒绝非法文件路径: {file_path}')
        return {'success': False, 'error': '非法文件路径', 'imported_count': 0}
    delete_file = True
    try:
        import openpyxl

        from fastapi_app.shared_models import StagingPurchasePlan
        session = (session_factory or _SyncSession)()
        try:
            batch_id = _batch_id_for_job(job_id)
            # 重放前先清掉同 batch 旧行：commit 后被杀再重试不会重复插入
            _clear_batch_rows(session, batch_id)
            session_id = str(user_id)
            wb = openpyxl.load_workbook(file_path, read_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(min_row=2, values_only=True))
            wb.close()
            # 第十轮审计：原无行数上界（对照 material_registration 5000 / case 20000）——
            # 超大文件会整表载入内存。与前端导入模板量级对齐，20000 行封顶。
            if len(rows) > 20000:
                raise ValueError(f'导入行数超限（{len(rows)} 行，上限 20000），请拆分文件后重试')
            success_count = 0
            errors = []
            detected_month = None
            for i, row in enumerate(rows, start=2):
                if not row or all(c is None for c in row):
                    continue
                try:
                    customer_name = str(row[0] or '').strip()
                    product_name = str(row[1] or '').strip()
                    barcode = str(row[2] or '').strip()
                    quantity = int(row[3]) if row[3] else 0
                    plan_date_str = str(row[4] or '').strip()
                    remark = str(row[5] or '').strip() if len(row) > 5 and row[5] else ''
                    if not customer_name or not barcode or quantity <= 0 or (not plan_date_str):
                        errors.append(f'第{i}行: 必填字段缺失或数量无效')
                        continue
                    # 2026-10-03 第八轮审计：此处原为 normalize_plan_date 的**旧副本**，
                    # 缺「剥时间部分」与「len(parts)!=3 守卫」——Excel 真日期单元格
                    # （openpyxl 读出 '2026-09-15 00:00:00'）会解析失败致整批静默丢弃；
                    # 畸形日期（如 '2026'）抛 IndexError 令任务崩溃、临时文件已删、
                    # ARQ 重试必"文件不存在"。改调权威实现 plan_utils.normalize_plan_date。
                    plan_date_val = normalize_plan_date(plan_date_str)
                    row_month = f'{plan_date_val.year}-{plan_date_val.month:02d}'
                    if detected_month is None:
                        detected_month = row_month
                    elif row_month != detected_month:
                        errors.append(f'第{i}行: 月份不一致')
                        continue
                    # savepoint 隔离单行：行内异常仅回滚本行，不影响已 add 的行
                    with session.begin_nested():
                        record = StagingPurchasePlan(session_id=session_id, customer_name=customer_name, product_name=product_name, barcode=barcode, quantity=quantity, plan_date=plan_date_val, plan_month=detected_month, remark=remark, is_validated=False, upload_batch_id=batch_id)
                        session.add(record)
                    # savepoint 成功提交后才计数，失败行不计入 success_count
                    success_count += 1
                except (ValueError, TypeError, OSError, SQLAlchemyError) as e:
                    # savepoint 已自动回滚本行，不再整体 rollback（避免误伤已成功的行）
                    errors.append(f'第{i}行: {e!s}')
            session.commit()
            return {'success': True, 'batch_id': batch_id, 'row_count': len(rows), 'success_count': success_count, 'error_count': len(errors), 'errors': errors[:50], 'task_id': job_id}
        finally:
            session.close()
    except (ValueError, TypeError, OSError) as exc:
        logger.error(f'批量计划导入任务失败: {exc}', exc_info=True)
        # 保留文件以供 ARQ 重试
        delete_file = False
        raise exc
    finally:
        if delete_file and file_path and os.path.exists(file_path):
            with contextlib.suppress(OSError):
                os.unlink(file_path)
