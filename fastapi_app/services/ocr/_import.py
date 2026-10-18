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

from fastapi_app.services.ocr._extractors import OcrDependencyError, extract_table_structure, extract_text
from fastapi_app.services.ocr._html_tables import (
    parse_html_shipping_tables,
    parse_shipping_document,
)
from fastapi_app.services.ocr._progress import _update_progress
from fastapi_app.services.ocr_fuzzy_match import fuzzy_match_customer, fuzzy_match_product
from fastapi_app.shared.stock_concurrency import check_stock_available
from fastapi_app.shared_models import Customer, Product, StagingStockOut

logger = logging.getLogger(__name__)




def _simulate_ocr_progress_steps() -> list[tuple[float, str]]:
    """文本 OCR 的模拟进度步（真实识别无回调，用固定节奏给前端反馈）。"""
    return [(35, '正在识别文字...'), (42, '正在提取文本内容...'), (50, '正在进行文字识别...'),
            (58, '正在整理识别结果...'), (65, '即将完成文本提取...')]


def _prog_fn(task_id: str):
    async def _prog(**kwargs):
        if task_id:
            await _update_progress(task_id, **kwargs)
    return _prog


async def _recognize_items(file_content: bytes, filename: str, file_type: str, _prog) -> tuple[list[dict], list, list]:
    """识别阶段：RapidTable 表格优先，失败/无表格回退文本 OCR + 字段解析。

    返回 (parsed_items, table_pages, text_pages)。
    """
    loop = asyncio.get_running_loop()
    parsed_items: list[dict] = []
    table_pages: list = []
    text_pages: list = []
    try:
        await _prog(message='正在识别表格结构...', percent=12)
        table_pages = await loop.run_in_executor(None, extract_table_structure, file_content, filename)
        if table_pages:
            parsed_items = parse_html_shipping_tables(table_pages)
            logger.info(f'RapidTable 表格识别: {filename}, 识别到 {len(table_pages)} 页表格, 解析出 {len(parsed_items)} 个出货项')
    except (ValueError, TypeError, OSError, RuntimeError) as e:
        # 2026-10-03 第八轮审计：_extractors 在 rapid_table 未装/初始化失败时抛
        # RuntimeError，原 except 未捕获 → 注释声明的"回退到文本模式"永不执行，
        # RuntimeError 冒泡成 500。补 RuntimeError 使回退真正生效。
        logger.warning(f'RapidTable 表格识别失败，将回退到文本模式: {e}')
    if parsed_items:
        return parsed_items, table_pages, text_pages

    await _prog(message='正在使用文本识别模式...', percent=30)
    ocr_future = loop.run_in_executor(None, extract_text, file_content, filename)
    steps = _simulate_ocr_progress_steps()

    async def _simulate_ocr_progress():
        for pct, msg in steps:
            await asyncio.sleep(0.4)
            await _prog(message=msg, percent=pct)

    sim_task = asyncio.create_task(_simulate_ocr_progress())
    try:
        text_pages = await ocr_future
    finally:
        sim_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sim_task
    if not text_pages:
        return [], table_pages, text_pages
    final_ocr_pct = 70
    await _prog(message=f'{file_type}文本提取完成，共 {len(text_pages)} 页', percent=final_ocr_pct)  # sql-safe: escape_like/绑定参数/常量片段
    await asyncio.sleep(0.05)
    logger.info(f"{file_type} OCR 提取完成: {filename}, 共 {len(text_pages)} 页, 文本长度: {sum(len(p['text']) for p in text_pages)}")  # sql-safe: escape_like/绑定参数/常量片段
    await _prog(message='正在解析出货单字段...', percent=75)
    await asyncio.sleep(0.05)
    parsed_items = parse_shipping_document(text_pages)
    return parsed_items, table_pages, text_pages


def _build_staging_row(session_id: str, item: dict, all_products: list,
                       product_map: dict, all_customers: list) -> StagingStockOut | None:
    """单个识别项 → StagingStockOut 行；跳过项（空产品名/非正数量）返回 None。"""
    product_name = str(item.get('product_name', '')).strip()
    customer = str(item.get('customer', '')).strip()
    quantity = item.get('quantity', 0)
    note = str(item.get('note', '')).strip()
    if not product_name or quantity <= 0:
        return None

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
        # 负库存判定统一走统一入口（P1-2b）；此处只产出暂存行的校验结论
        if check_stock_available(product.current_stock, -quantity) is not None:
            stock_check_message = f'库存不足，当前库存: {product.current_stock}'
        else:
            stock_check_passed = True
            stock_check_message = f'库存充足，当前库存: {product.current_stock}'
    else:
        validation_error = f'产品"{product_name}"不存在'
    if match_info_parts:
        note = note + '；' + '；'.join(match_info_parts) if note else '；'.join(match_info_parts)

    # stockout_date aware UTC：staging_stock_out.stockout_date 列为 timestamptz
    row = StagingStockOut(session_id=session_id, customer=customer, stockout_date=datetime.now(UTC), product_name=product_name, product_barcode='', product_id=product_id, quantity=quantity, note=note, is_validated=is_validated, validation_error=validation_error, stock_check_passed=stock_check_passed, stock_check_message=stock_check_message, status='pending')
    return row

async def import_staging_stockouts_from_file(db: AsyncSession, file_content: bytes, session_id: str, filename: str='', task_id: str='') -> tuple[int, str, list[str]]:
    """
    从 PDF / 图片出货单导入出货到暂存区（2026-10-11 复核 P2-14⑥ 拆分）。

    流程: 识别（表格→文本回退）→ 匹配校验 → 写入暂存区；
    各阶段见 _recognize_items / _build_staging_row。
    """
    _prog = _prog_fn(task_id)
    try:
        async with db.begin_nested():  # SAVEPOINT：失败只回滚本文件，不触碰调用方事务（原先裸 db.rollback() 会把同批次前面文件已写入的暂存行一起回滚）
            ext = os.path.splitext(filename or '')[1].lower()
            is_pdf = ext == '.pdf'
            file_type = 'PDF' if is_pdf else '图片'
            await _prog(status='processing', message=f'正在识别 {filename}...', filename=filename, percent=5)
            await asyncio.sleep(0)
            if is_pdf:
                await _prog(message=f'正在加载 PDF {filename}...', percent=8)
            else:
                await _prog(message=f'正在读取图片 {filename}...', percent=8)
            await asyncio.sleep(0)

            parsed_items, table_pages, text_pages = await _recognize_items(file_content, filename, file_type, _prog)
            if not text_pages and not parsed_items:
                await _prog(message='文件无法提取文本内容', percent=0)
                return (0, '文件无法提取文本内容，可能是空白文件或图片质量过低', [])
            if not parsed_items:
                preview_pages = table_pages or text_pages
                raw_text_preview = '\n'.join(p.get('text', '')[:200] for p in preview_pages[:3])
                logger.warning(f'{file_type} 解析未识别到出货项: {filename}\n原始文本:\n{raw_text_preview}')  # sql-safe: escape_like/绑定参数/常量片段
                await _prog(message='无法识别出货信息', percent=0)
                return (0, '无法从文件中识别出货信息，请确认文件格式是否正确', [])
            await _prog(message=f'解析完成，识别到 {len(parsed_items)} 个出货项', percent=80)
            await asyncio.sleep(0.05)
            await _prog(message='正在匹配产品和客户...', percent=85)
            await asyncio.sleep(0.05)
            result = await db.execute(select(Product))
            all_products = list(result.scalars().all())
            product_map = {p.name.lower().strip(): p for p in all_products}
            product_map.update({p.barcode: p for p in all_products if p.barcode})
            result = await db.execute(select(Customer))
            all_customers = list(result.scalars().all())
            await _prog(message=f'正在写入暂存区（共{len(parsed_items)}项）...', percent=90)
            await asyncio.sleep(0.05)
            imported = 0
            errors = []
            total = len(parsed_items)
            for idx, item in enumerate(parsed_items, start=1):
                try:
                    if total > 1 and (idx % 5 == 0 or idx == total):
                        item_pct = 90 + int(idx / total * 6)
                        await _prog(message=f'正在处理第 {idx}/{total} 项...', percent=item_pct)
                        await asyncio.sleep(0.02)
                    row = _build_staging_row(session_id, item, all_products, product_map, all_customers)
                    if row is None:  # 跳过项（空产品名/非正数量）
                        continue
                    db.add(row)
                    imported += 1
                except (ValueError, TypeError, OSError) as e:
                    errors.append(f'第{idx}项处理失败: {e!s}')
                    continue
            await _prog(message='正在保存到数据库...', percent=98)
            await asyncio.sleep(0.05)
            await db.flush()
            result_msg = f'成功从{file_type}识别并导入 {imported} 个出货到暂存区'
            if errors:
                result_msg += f"。错误: {'; '.join(errors[:5])}"
            # 2026-10-18 OCR 评审：单文件完成不得写批量终态 done——同一 task_id
            # 被整批共享，写 done 会让前端在第一个文件后就停止轮询。
            await _prog(message=result_msg, percent=100)
            return (imported, result_msg, errors[:10] if errors else [])
    except OcrDependencyError:
        # 2026-10-18 OCR 评审：OcrDependencyError 继承 RuntimeError，必须先于
        # 下面的宽泛捕获重抛，否则端点的「缺依赖」专门分支永远不可达。
        raise
    except (ValueError, TypeError, OSError, RuntimeError) as e:
        # 2026-10-03 第八轮审计：补 RuntimeError —— extract_text 在 rapidocr 未装/初始化
        # 失败时抛 RuntimeError，原 except 未捕获会冒泡成 500；此处应优雅返回失败元组。
        logger.error(f'OCR 导入失败: {e!s}', exc_info=True)
        await _prog(message=f'识别导入失败: {e!s}', percent=0)
        return (0, f'识别导入失败: {e!s}', [])


import_staging_stockouts_from_pdf = import_staging_stockouts_from_file
