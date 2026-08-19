"""
采购计划相关异步任务

- 出货数据每日同步（ARQ cron 定时任务）
- 批量计划导入（>500行时异步处理）

使用 SyncSessionLocal + shared_models，同步 DB 操作通过 asyncio.to_thread 运行。
"""
import asyncio
import contextlib
import os
import tempfile
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from fastapi_app.core.database import get_sync_engine
from fastapi_app.core.logger import logger

_SyncSession = sessionmaker(
    autocommit=False, autoflush=False, bind=get_sync_engine()
)


async def sync_shipment_records_task(ctx):
    """
    每日凌晨同步出货数据

    从 stock_out 表同步昨日数据到 shipment_records 表，
    并刷新 purchase_plan_details.shipped_qty 缓存。
    """
    def _sync_impl():
        try:
            from sqlalchemy import text
            session = _SyncSession()
            try:
                target_date = datetime.now(UTC).replace(tzinfo=None).date() - timedelta(days=1)
                rows = session.execute(text("\n                SELECT so.id, so.stockout_no, so.customer, so.product_id,\n                       so.quantity, so.returned_quantity, DATE(so.stockout_date) as stockout_date,\n                       p.name as product_name\n                FROM stock_out so\n                JOIN product p ON so.product_id = p.id\n                WHERE DATE(so.stockout_date) = :target_date\n                  AND so.customer IS NOT NULL AND so.customer != ''\n            "), {'target_date': target_date}).fetchall()
                customers = session.execute(text('SELECT id, name FROM customer')).fetchall()
                customer_id_map = {c.name: c.id for c in customers}
                synced_count = 0
                for row in rows:
                    customer_id = customer_id_map.get(row.customer)
                    if not customer_id:
                        continue
                    existing = session.execute(text('SELECT id FROM shipment_records WHERE shipment_no = :no'), {'no': row.stockout_no}).fetchone()
                    if existing:
                        session.execute(text('\n                        UPDATE shipment_records\n                        SET quantity = :qty, synced_at = NOW()\n                        WHERE shipment_no = :no\n                    '), {'qty': row.quantity - row.returned_quantity, 'no': row.stockout_no})
                    else:
                        session.execute(text("\n                        INSERT INTO shipment_records\n                            (shipment_no, customer_id, customer_name, product_id,\n                             product_name, quantity, shipment_date, source_type,\n                             source_id, synced_at)\n                        VALUES (:no, :cid, :cname, :pid, :pname, :qty,\n                                :sdate, 'stockout', :sid, NOW())\n                    "), {'no': row.stockout_no, 'cid': customer_id, 'cname': row.customer, 'pid': row.product_id, 'pname': row.product_name, 'qty': row.quantity - row.returned_quantity, 'sdate': row.stockout_date, 'sid': row.id})
                    synced_count += 1
                session.commit()
                logger.info(f'出货记录同步完成：{target_date}，{synced_count}条')
                return {'success': True, 'synced_count': synced_count, 'target_date': target_date.isoformat()}
            finally:
                session.close()
        except (ValueError, TypeError, OSError) as exc:
            logger.error(f'出货同步任务失败: {exc}', exc_info=True)
            raise exc

    return await asyncio.to_thread(_sync_impl)


async def batch_import_plans_task(ctx, file_path: str, original_filename: str, user_id: int):
    """
    大批量计划导入（>500行时由API层触发）

    输入：临时文件路径、原始文件名、用户ID
    处理：解析 Excel → 写入 staging → 返回 batch_id
    """
    job_id = ctx['job_id']

    def _sync_impl():
        allowed_dirs = [tempfile.gettempdir(), os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'static', 'uploads')]
        real_path = os.path.realpath(file_path)
        if not any(os.path.commonpath([real_path, d]) == d for d in allowed_dirs if os.path.exists(d)):
            logger.error(f'批量计划导入任务拒绝非法文件路径: {file_path}')
            return {'success': False, 'error': '非法文件路径', 'imported_count': 0}
        delete_file = True
        try:
            import uuid

            import openpyxl

            from fastapi_app.shared_models import StagingPurchasePlan
            session = _SyncSession()
            try:
                batch_id = str(uuid.uuid4())[:8]
                session_id = str(user_id)
                wb = openpyxl.load_workbook(file_path, read_only=True)
                ws = wb.active
                rows = list(ws.iter_rows(min_row=2, values_only=True))
                wb.close()
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
                        import calendar
                        from datetime import datetime
                        try:
                            plan_date_val = datetime.strptime(plan_date_str, '%Y-%m-%d').date()
                        except ValueError:
                            parts = plan_date_str.strip().split('-')
                            y, m = (int(parts[0]), int(parts[1]))
                            d = min(int(parts[2]), calendar.monthrange(y, m)[1])
                            plan_date_val = datetime(y, m, d).date()
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

    return await asyncio.to_thread(_sync_impl)
