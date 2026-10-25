"""皮套序列化辅助（SKU 主档 / 出入库流水）"""
from fastapi_app.core.business_time import fmt_business
from fastapi_app.shared_models import Case, CaseMovement


def _serialize_item(c: Case) -> dict:
    """将皮套 SKU 序列化为字典。

    只读本表字段：**不要**用 `c.sync_name`/`c.sync_barcode`——那会懒加载
    `product` 关系，在 async 会话里触发 IO 报 MissingGreenlet。
    """
    return {
        'id': c.id,
        'name': c.name or '',
        'barcode': c.barcode or '',
        'image': c.image or '',
        'unit': c.unit or '',
        'product_id': c.product_id,
        'parent_id': c.parent_id,
        'qty_per_set': c.qty_per_set if c.qty_per_set is not None else 1,
        'initial_stock': c.initial_stock or 0,
        'current_stock': c.current_stock or 0,
    }


def _serialize_movement(m: CaseMovement) -> dict:
    """将出入库流水序列化为字典。"""
    return {
        'id': m.id,
        'case_id': m.case_id,
        'case_name': m.case.name if m.case else '',
        'case_barcode': (m.case.barcode or '') if m.case else '',
        'direction': m.direction,
        'movement_no': m.movement_no,
        'quantity': m.quantity,
        'customer': m.customer or '',
        'movement_date': fmt_business(m.movement_date, '%Y-%m-%d'),
        'note': m.note or '',
        'create_time': fmt_business(m.create_time, '%Y-%m-%d %H:%M:%S'),
    }
