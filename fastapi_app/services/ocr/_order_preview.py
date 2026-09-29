"""订单 OCR 预览（识别 + 匹配，**不写库**）

与 `_import.py`（出货单导入）的区别：出货单识别后直接写 `staging_stock_out`；
订单这里是**预览**语义——结果交给前端在弹窗里人工确认、改正后再进暂存区，
所以本模块不产生任何写入。
"""
import asyncio
import logging
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.services.ocr._extractors import extract_text
from fastapi_app.services.ocr._order_match import match_product_robust
from fastapi_app.services.ocr._order_parsers import parse_order_document
from fastapi_app.services.ocr_fuzzy_match import fuzzy_match_customer
from fastapi_app.shared_models import Customer, Product

logger = logging.getLogger(__name__)

# 模糊匹配的采纳阈值。低于此值只展示候选置信度，不替用户拍板。
MIN_MATCH_CONFIDENCE = 0.7

# 回给前端的识别原文上限（用于区分「认字错了」还是「解析错了」）
RAW_TEXT_LIMIT = 2000

# fuzzy_match_* 的返回标注是 object|None（共享模块，本次不改它），
# 这里 cast 回真实模型类型；无需运行时校验，故不影响 mock 测试。


def _match_product(raw_name: str, all_products: list, product_map: dict) -> tuple[object | None, float]:
    """匹配产品，返回 (产品 | None, 置信度)。

    用 `_order_match.match_product_robust`：共享匹配器不中时，还会按「原图文字
    包含库内产品名的多少」兜底——OCR 把备注/邻列粘到产品名上时，真正用到的名称
    仍要能被认出来（详见该模块说明）。
    """
    matched, confidence = match_product_robust(raw_name, all_products, product_map)
    return cast('Product | None', matched), float(confidence)


def _resolve_customer(
    name: str,
    default_customer: str,
    all_customers: list,
) -> tuple[str, int | None, float, bool]:
    """确定客户，返回 (客户名, 客户ID|None, 置信度, 是否用了表单兜底)

    图上没有客户信息时用表单已选客户兜底（对应需求「无法识别到客户信息时给替代方案」）。
    """
    used_default = False
    if not name and default_customer:
        name = default_customer
        used_default = True
    if not name:
        return '', None, 0.0, used_default
    matched, confidence = fuzzy_match_customer(name, all_customers)
    customer = cast('Customer | None', matched)
    if customer is not None and confidence >= MIN_MATCH_CONFIDENCE:
        return customer.name, customer.id, float(confidence), used_default
    return name, None, float(confidence), used_default


def _build_item(entry: dict, product: object | None, product_confidence: float,
                customer: tuple[str, int | None, float, bool]) -> dict:
    raw_name = entry['product_name']
    customer_name, customer_id, customer_confidence, _ = customer
    return {
        'raw_product_name': raw_name,
        'product_id': getattr(product, 'id', None),
        'product_name': getattr(product, 'name', None) or raw_name,
        'match_confidence': round(product_confidence, 4),
        'quantity': entry['quantity'],
        'unit': entry['unit'],
        'customer': customer_name,
        'customer_id': customer_id,
        'customer_confidence': round(customer_confidence, 4),
        'note': entry['note'],
    }


def _collect_warnings(items: list[dict], unmatched: int, used_default_customer: bool) -> list[str]:
    warnings: list[str] = []
    if unmatched:
        warnings.append(f'{unmatched} 项产品在库内没有匹配，需要手动选择')
    if used_default_customer:
        warnings.append('图上没有客户信息，已按当前选择的客户填入')
    if not any(item['customer'] for item in items):
        warnings.append('没有识别到客户，请先在表单选择客户')
    return warnings


async def preview_order_items(
    db: AsyncSession,
    file_content: bytes,
    filename: str = '',
    default_customer: str = '',
) -> tuple[list[dict], str, list[str]]:
    """识别订单图片/PDF，返回待人工确认的条目。

    Args:
        db: 异步数据库会话（只读，用于取产品/客户做匹配）
        file_content: 文件字节内容
        filename: 原始文件名（决定按图片还是 PDF 识别）
        default_customer: 表单当前已选客户名，图上没有客户信息时兜底

    Returns:
        (items, raw_text, warnings)
    """
    pages = await asyncio.to_thread(extract_text, file_content, filename)
    raw_text = '\n'.join(p.get('text', '') for p in pages)[:RAW_TEXT_LIMIT]
    parsed = parse_order_document(pages)
    if not parsed:
        return [], raw_text, []

    # 只取匹配真正用到的列：全表 ORM 实体化在每次粘贴时都做一遍，纯属浪费
    # （fuzzy_match_* 只读 name，product_map 另需 barcode）。
    product_rows = await db.execute(select(Product.id, Product.name, Product.barcode))
    all_products = list(product_rows.all())
    product_map = {p.name.lower().strip(): p for p in all_products}
    product_map.update({p.barcode: p for p in all_products if p.barcode})

    customer_rows = await db.execute(select(Customer.id, Customer.name))
    all_customers = list(customer_rows.all())

    items: list[dict] = []
    unmatched = 0
    used_default_customer = False
    for entry in parsed:
        product, product_confidence = _match_product(entry['product_name'], all_products, product_map)
        if product is None:
            unmatched += 1
        customer = _resolve_customer(entry['customer'], default_customer, all_customers)
        used_default_customer = used_default_customer or customer[3]
        items.append(_build_item(entry, product, product_confidence, customer))

    warnings = _collect_warnings(items, unmatched, used_default_customer)
    logger.info('OCR 订单预览: %s, 解析 %d 项, 未匹配产品 %d 项', filename, len(items), unmatched)
    return items, raw_text, warnings
