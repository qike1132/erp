"""OCR 出货单导入暂存区

从 ocr_service.py 按职责拆出,行为与原实现完全一致。
"""
import asyncio
import contextlib
import logging
import os
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.services.ocr._extractors import extract_table_structure, extract_text
from fastapi_app.services.ocr._progress import _update_progress
from fastapi_app.services.ocr._html_tables import (
    parse_html_shipping_tables,
    parse_shipping_document,
)
from fastapi_app.services.ocr_fuzzy_match import fuzzy_match_customer, fuzzy_match_product
from fastapi_app.shared_models import Customer, Product, StagingStockOut

logger = logging.getLogger(__name__)


async def import_staging_stockouts_from_file(db: AsyncSession, file_content: bytes, session_id: str, filename: str='', task_id: str='') -> tuple[int, str, list[str]]:
    """
    从 PDF / 图片出货单导入出货到暂存区

    流程:
    1. 根据文件类型自动选择 PDF 或图片 OCR 提取文本
    2. 解析出货单字段
    3. 匹配产品、校验库存
    4. 写入暂存区

    Args:
        db: 异步数据库会话
        file_content: 文件字节内容
        session_id: 会话 ID
        filename: 原始文件名（用于日志和类型判断）
        task_id: 进度追踪 ID（可选）

    Returns:
        (imported_count, message, errors)
    """

    def _prog(**kwargs):
        if task_id:
            _update_progress(task_id, **kwargs)
    try:
        _prog(status='processing', message=f'正在识别 {filename}...', filename=filename, percent=5)
        await asyncio.sleep(0)
        ext = os.path.splitext(filename or '')[1].lower()
        is_pdf = ext == '.pdf'
        file_type = 'PDF' if is_pdf else '图片'
        if is_pdf:
            _prog(message=f'正在加载 PDF {filename}...', percent=8)
        else:
            _prog(message=f'正在读取图片 {filename}...', percent=8)
        await asyncio.sleep(0)
        loop = asyncio.get_running_loop()
        parsed_items = []
        table_pages = []
        text_pages = []
        try:
            _prog(message='正在识别表格结构...', percent=12)
            table_pages = await loop.run_in_executor(None, extract_table_structure, file_content, filename)
            if table_pages:
                parsed_items = parse_html_shipping_tables(table_pages)
                logger.info(f'RapidTable 表格识别: {filename}, 识别到 {len(table_pages)} 页表格, 解析出 {len(parsed_items)} 个出货项')
        except (ValueError, TypeError, OSError) as e:
            logger.warning(f'RapidTable 表格识别失败，将回退到文本模式: {e}')
        if not parsed_items:
            _prog(message='正在使用文本识别模式...', percent=30)
            ocr_future = loop.run_in_executor(None, extract_text, file_content, filename)
            _ocr_simulated_pct = 30
            _ocr_simulated_msgs = [(35, '正在识别文字...'), (42, '正在提取文本内容...'), (50, '正在进行文字识别...'), (58, '正在整理识别结果...'), (65, '即将完成文本提取...')]

            async def _simulate_ocr_progress():
                nonlocal _ocr_simulated_pct
                for pct, msg in _ocr_simulated_msgs:
                    await asyncio.sleep(0.4)
                    _ocr_simulated_pct = pct
                    _prog(message=msg, percent=pct)
            sim_task = asyncio.create_task(_simulate_ocr_progress())
            try:
                text_pages = await ocr_future
            finally:
                sim_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await sim_task
            if not text_pages:
                _prog(status='error', message='文件无法提取文本内容', percent=0)
                return (0, '文件无法提取文本内容，可能是空白文件或图片质量过低', [])
            final_ocr_pct = max(70, _ocr_simulated_pct)
            _prog(message=f'{file_type}文本提取完成，共 {len(text_pages)} 页', percent=final_ocr_pct)  # sql-safe: escape_like/绑定参数/常量片段
            await asyncio.sleep(0.05)
            logger.info(f"{file_type} OCR 提取完成: {filename}, 共 {len(text_pages)} 页, 文本长度: {sum(len(p['text']) for p in text_pages)}")  # sql-safe: escape_like/绑定参数/常量片段
            _prog(message='正在解析出货单字段...', percent=75)
            await asyncio.sleep(0.05)
            parsed_items = parse_shipping_document(text_pages)
        if not parsed_items:
            preview_pages = table_pages or text_pages
            raw_text_preview = '\n'.join(p.get('text', '')[:200] for p in preview_pages[:3])
            logger.warning(f'{file_type} 解析未识别到出货项: {filename}\n原始文本:\n{raw_text_preview}')  # sql-safe: escape_like/绑定参数/常量片段
            _prog(status='error', message='无法识别出货信息', percent=0)
            return (0, '无法从文件中识别出货信息，请确认文件格式是否正确', [])
        _prog(message=f'解析完成，识别到 {len(parsed_items)} 个出货项', percent=80)
        await asyncio.sleep(0.05)
        _prog(message='正在匹配产品和客户...', percent=85)
        await asyncio.sleep(0.05)
        result = await db.execute(select(Product))
        all_products = result.scalars().all()
        product_map = {p.name.lower().strip(): p for p in all_products}
        product_map.update({p.barcode: p for p in all_products if p.barcode})
        result = await db.execute(select(Customer))
        all_customers = result.scalars().all()
        _prog(message=f'正在写入暂存区（共{len(parsed_items)}项）...', percent=90)
        await asyncio.sleep(0.05)
        imported = 0
        errors = []
        for idx, item in enumerate(parsed_items, start=1):
            try:
                product_name = str(item.get('product_name', '')).strip()
                customer = str(item.get('customer', '')).strip()
                quantity = item.get('quantity', 0)
                note = str(item.get('note', '')).strip()
                if not product_name or quantity <= 0:
                    continue
                if len(parsed_items) > 1 and (idx % 5 == 0 or idx == len(parsed_items)):
                    item_pct = 90 + int(idx / len(parsed_items) * 6)
                    _prog(message=f'正在处理第 {idx}/{len(parsed_items)} 项...', percent=item_pct)
                    await asyncio.sleep(0.02)
                product, match_confidence = fuzzy_match_product(product_name, all_products, product_map)
                matched_customer, customer_confidence = fuzzy_match_customer(customer, all_customers)
                if matched_customer and customer_confidence >= 0.7:
                    if customer_confidence < 1.0:
                        logger.info(f"客户模糊匹配: OCR='{customer}' -> DB='{matched_customer.name}', 置信度={customer_confidence:.2f}")
                    customer = matched_customer.name
                is_validated = False
                validation_error = ''
                product_id = None
                stock_check_passed = False
                stock_check_message = ''
                match_info_parts = []
                if product:
                    is_validated = True
                    product_id = product.id
                    original_ocr_name = product_name
                    product_name = product.name
                    if match_confidence < 1.0:
                        match_info_parts.append(f"产品模糊匹配: OCR='{original_ocr_name}'→'{product_name}'({match_confidence:.0%})")
                    if product.current_stock < quantity:
                        stock_check_message = f'库存不足，当前库存: {product.current_stock}'
                    else:
                        stock_check_passed = True
                        stock_check_message = f'库存充足，当前库存: {product.current_stock}'
                else:
                    validation_error = f'产品"{product_name}"不存在'
                if match_info_parts:
                    note = note + '；' + '；'.join(match_info_parts) if note else '；'.join(match_info_parts)
                staging_stockout = StagingStockOut(session_id=session_id, customer=customer, stockout_date=datetime.now(UTC).replace(tzinfo=None), product_name=product_name, product_barcode='', product_id=product_id, quantity=quantity, note=note, is_validated=is_validated, validation_error=validation_error, stock_check_passed=stock_check_passed, stock_check_message=stock_check_message, status='pending')
                db.add(staging_stockout)
                imported += 1
            except (ValueError, TypeError, OSError) as e:
                errors.append(f'第{idx}项处理失败: {e!s}')
                continue
        _prog(message='正在保存到数据库...', percent=98)
        await asyncio.sleep(0.05)
        await db.flush()
        result_msg = f'成功从{file_type}识别并导入 {imported} 个出货到暂存区'
        if errors:
            result_msg += f"。错误: {'; '.join(errors[:5])}"
        _prog(status='done', message=result_msg, percent=100)
        return (imported, result_msg, errors[:10] if errors else [])
    except (ValueError, TypeError, OSError) as e:
        await db.rollback()  # manual-tx: try/except 内显式事务控制
        logger.error(f'OCR 导入失败: {e!s}', exc_info=True)
        _prog(status='error', message=f'识别导入失败: {e!s}', percent=0)
        return (0, f'识别导入失败: {e!s}', [])
import_staging_stockouts_from_pdf = import_staging_stockouts_from_file