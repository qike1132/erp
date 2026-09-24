"""皮套序列化辅助

从 case_service.py 按职责拆出,行为与原实现完全一致。
"""
from fastapi_app.shared_models import CaseStockIn, CaseStockOut


def _serialize_stockin(stockin: CaseStockIn) -> dict:
    """将入库记录对象序列化为字典。

    Args:
        stockin: CaseStockIn 对象。

    Returns:
        包含入库记录字段的字典。
    """
    return {
        'id': stockin.id, 'stockin_no': stockin.stockin_no,
        'stockin_date': stockin.stockin_date.strftime('%Y-%m-%d') if stockin.stockin_date else '',
        'customer': stockin.customer, 'case_id': stockin.case_id,
        'case_name': stockin.case.sync_name if stockin.case else '',
        'case_barcode': stockin.case.sync_barcode if stockin.case else '',
        'quantity': stockin.quantity, 'note': stockin.note or '',
    }

def _serialize_stockout(stockout: CaseStockOut) -> dict:
    """将出库记录对象序列化为字典。

    Args:
        stockout: CaseStockOut 对象。

    Returns:
        包含出库记录字段的字典。
    """
    return {
        'id': stockout.id, 'stockout_no': stockout.stockout_no,
        'stockout_date': stockout.stockout_date.strftime('%Y-%m-%d') if stockout.stockout_date else '',
        'customer': stockout.customer or '', 'case_id': stockout.case_id,
        'case_name': stockout.case.sync_name if stockout.case else '',
        'case_barcode': stockout.case.sync_barcode if stockout.case else '',
        'quantity': stockout.quantity, 'note': stockout.note or '',
    }
