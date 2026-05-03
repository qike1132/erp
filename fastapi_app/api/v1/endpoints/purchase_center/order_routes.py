"""
采购中心 — 采购订单 CRUD 路由
"""
import hashlib
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import DisconnectionError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi_app.api.v1.endpoints.purchase_center.schemas import (
    BatchCompleteRequest,
    ExportCompletedRequest,
    FactorySummarySaveRequest,
    OneClickGenerateRequest,
    OrderIdRequest,
    OrderIdsAltRequest,
    OrderIdsRequest,
    PurchaseOrderCreateRequest,
    PurchaseOrderUpdateRequest,
)
from fastapi_app.core.database import get_sync_db as get_db
from fastapi_app.core.deps import require_permission
from fastapi_app.core.logger import logger
from fastapi_app.core.purchase_cache import register_purchase_cache
from fastapi_app.services import purchase_center_service as svc

router = APIRouter()
_ORDERS_L1_CACHE: dict[str, tuple[float, dict]] = {}
_ORDERS_CACHE_TTL = 60
_UNPROCESSED_L1_CACHE: dict[str, tuple[float, dict]] = {}
_UNPROCESSED_CACHE_TTL = 10

register_purchase_cache(_ORDERS_L1_CACHE)
register_purchase_cache(_UNPROCESSED_L1_CACHE)

def _make_orders_cache_key(**kwargs) -> str:
    raw = json.dumps(kwargs, sort_keys=True, default=str)
    return hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()

def _invalidate_orders_cache():
    _ORDERS_L1_CACHE.clear()
    _UNPROCESSED_L1_CACHE.clear()
    try:
        from fastapi_app.core.cache import invalidate_local_cache
        invalidate_local_cache('orders:*')
    except (OSError, ValueError):
        logger.warning('缓存失效失败(order_routes)', exc_info=True)

@router.post('/orders')
def api_create_purchase_order(data: PurchaseOrderCreateRequest, db: Session=Depends(get_db), _user=Depends(require_permission('product_manage'))):
    try:
        result = svc.create_purchase_order(db, data.model_dump(), _user.id, _user.username)
        db.commit()
        _invalidate_orders_cache()
        return {'success': True, **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (SQLAlchemyError, RuntimeError) as e:
        db.rollback()
        logger.error(f'创建采购订单失败: {e}')
        raise HTTPException(status_code=500, detail='创建订单失败，请稍后重试') from e

@router.post('/orders/one-click-generate')
def api_one_click_generate_order(data: OneClickGenerateRequest, db: Session=Depends(get_db), _user=Depends(require_permission('product_manage'))):
    try:
        result = svc.one_click_generate_order(db, data.order_ids, _user.id, _user.username)
        _invalidate_orders_cache()
        return {'success': True, **result}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (SQLAlchemyError, RuntimeError) as e:
        db.rollback()
        logger.exception(f'一键生成采购订单失败: {str(e)}')
        raise HTTPException(status_code=500, detail='生成采购订单失败，请稍后重试') from e

@router.get('/orders')
def api_get_purchase_orders(page: int=Query(1, ge=1), per_page: int=Query(20, ge=1), status: str=Query('', max_length=50), customer: str=Query('', max_length=100), product_name: str=Query('', max_length=100), start_date: str=Query('', max_length=20), end_date: str=Query('', max_length=20), order_no: str=Query('', max_length=50), supplier: str=Query('', max_length=100), db: Session=Depends(get_db), _user=Depends(require_permission('product_manage'))):
    cache_key = _make_orders_cache_key(page=page, per_page=per_page, status=status, customer=customer, product_name=product_name, start_date=start_date, end_date=end_date, order_no=order_no, supplier=supplier)
    entry = _ORDERS_L1_CACHE.get(cache_key)
    if entry is not None:
        cached_at, cached_result = entry
        if time.monotonic() - cached_at < _ORDERS_CACHE_TTL:
            return {'success': True, **cached_result}
        del _ORDERS_L1_CACHE[cache_key]
    result = svc.get_purchase_orders(db, page=page, per_page=per_page, status=status, customer=customer, product_name=product_name, start_date=start_date, end_date=end_date, order_no=order_no, supplier=supplier)
    _ORDERS_L1_CACHE[cache_key] = (time.monotonic(), result)
    if len(_ORDERS_L1_CACHE) > 100:
        oldest_key = min(_ORDERS_L1_CACHE, key=lambda k: _ORDERS_L1_CACHE[k][0])
        del _ORDERS_L1_CACHE[oldest_key]
    return {'success': True, **result}

@router.get('/orders/completed')
def api_get_completed_purchase_orders(page: int=Query(1, ge=1), per_page: int=Query(20, ge=1), order_no: str=Query('', max_length=50), customer_name: str=Query('', max_length=100), product_name: str=Query('', max_length=100), supplier_name: str=Query('', max_length=100), barcode: str=Query('', max_length=50), material_name: str=Query('', max_length=100), start_date: str=Query('', max_length=20), end_date: str=Query('', max_length=20), db: Session=Depends(get_db), _user=Depends(require_permission('product_manage'))):
    result = svc.get_completed_purchase_orders(db, page=page, per_page=per_page, order_no=order_no, customer_name=customer_name, product_name=product_name, supplier_name=supplier_name, barcode=barcode, material_name=material_name, start_date=start_date, end_date=end_date)
    return {'success': True, **result}

@router.post('/orders/completed/export')
def api_export_completed_orders(data: ExportCompletedRequest, db: Session=Depends(get_db), _user=Depends(require_permission('product_manage'))):
    html = svc.export_completed_orders(db, data.model_dump(exclude_none=True))
    return {'success': True, 'html': html}

@router.get('/orders/completed/suggestions')
def api_get_completed_order_suggestions(field: str=Query(''), q: str=Query(''), limit: int=Query(10, ge=1, le=50), db: Session=Depends(get_db), _user=Depends(require_permission('product_manage'))):
    suggestions = svc.get_completed_order_suggestions(db, field, q, limit)
    return {'success': True, 'suggestions': suggestions}

@router.get('/orders/completed/quick-filters')
async def api_get_completed_order_quick_filters(_user=Depends(require_permission('product_manage'))):
    quick_filters = svc.get_completed_order_quick_filters()
    return {'success': True, 'quick_filters': quick_filters}

@router.get('/orders/{order_id}')
def api_get_purchase_order(order_id: int, db: Session=Depends(get_db), _user=Depends(require_permission('product_manage'))):
    result = svc.get_purchase_order(db, order_id)
    if not result:
        raise HTTPException(status_code=404, detail='订单不存在')
    return {'success': True, 'order': result}

@router.put('/orders/{order_id}')
def api_update_purchase_order(order_id: int, data: PurchaseOrderUpdateRequest, db: Session=Depends(get_db), _user=Depends(require_permission('product_manage'))):
    result = svc.update_purchase_order(db, order_id, data.model_dump(exclude_unset=True), _user.username)
    if not result:
        raise HTTPException(status_code=404, detail='订单不存在')
    _invalidate_orders_cache()
    return {'success': True, 'order': result}

@router.delete('/orders/{order_id}')
def api_delete_purchase_order(order_id: int, db: Session=Depends(get_db), _user=Depends(require_permission('product_manage'))):
    result = svc.delete_purchase_order(db, order_id)
    if not result:
        raise HTTPException(status_code=404, detail='订单不存在')
    _invalidate_orders_cache()
    return {'success': True, 'message': result}

@router.post('/orders/complete')
def api_complete_purchase_order(data: OrderIdRequest, db: Session=Depends(get_db), _user=Depends(require_permission('product_manage'))):
    try:
        result = svc.complete_purchase_order(db, data.order_id, _user.id, _user.username)
        _invalidate_orders_cache()
        return {'success': True, **result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (SQLAlchemyError, RuntimeError) as e:
        db.rollback()
        logger.error(f'完成订单失败: {e}')
        raise HTTPException(status_code=500, detail='完成订单失败，请稍后重试') from e

@router.post('/orders/batch-complete')
def api_batch_complete_purchase_orders(data: BatchCompleteRequest, db: Session=Depends(get_db), _user=Depends(require_permission('product_manage'))):
    try:
        result = svc.batch_complete_purchase_orders(db, data.ids, _user.id, _user.username)
        _invalidate_orders_cache()
        return {'success': True, **result}
    except (ValueError, SQLAlchemyError, RuntimeError):
        db.rollback()
        raise HTTPException(status_code=500, detail='完成订单失败，请稍后重试') from None

@router.post('/orders/batch-delete')
def api_batch_delete_purchase_orders(data: OrderIdsAltRequest, db: Session=Depends(get_db), _user=Depends(require_permission('product_manage'))):
    """批量删除采购订单"""
    try:
        result = svc.batch_delete_purchase_orders(db, data.order_ids)
        _invalidate_orders_cache()
        return {'success': True, **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

@router.get('/orders/{order_id}/print')
def api_get_order_print_data(order_id: int, db: Session=Depends(get_db), _user=Depends(require_permission('product_manage'))):
    result = svc.get_purchase_order(db, order_id)
    if not result:
        raise HTTPException(status_code=404, detail='订单不存在')
    return {'success': True, 'order': result}

@router.post('/orders/batch-print')
def api_get_orders_batch_print_data(data: OrderIdsRequest, db: Session=Depends(get_db), _user=Depends(require_permission('product_manage'))):
    from fastapi_app.shared_models import PurchaseOrder
    orders = db.query(PurchaseOrder).filter(PurchaseOrder.id.in_(data.ids)).all()
    return {'success': True, 'orders': [o.to_dict() for o in orders]}

@router.get('/unprocessed-orders')
def api_get_unprocessed_orders(customer: str=Query(''), page: int=Query(1, ge=1), per_page: int=Query(50, ge=1), db: Session=Depends(get_db), _user=Depends(require_permission('product_manage'))):
    cache_key = _make_orders_cache_key(endpoint='unprocessed', customer=customer, page=page, per_page=per_page)
    entry = _UNPROCESSED_L1_CACHE.get(cache_key)
    if entry is not None:
        cached_at, cached_result = entry
        if time.monotonic() - cached_at < _UNPROCESSED_CACHE_TTL:
            return {'success': True, **cached_result}
        del _UNPROCESSED_L1_CACHE[cache_key]
    result = svc.get_unprocessed_orders(db, customer=customer, page=page, per_page=per_page)
    _UNPROCESSED_L1_CACHE[cache_key] = (time.monotonic(), result)
    if len(_UNPROCESSED_L1_CACHE) > 50:
        oldest_key = min(_UNPROCESSED_L1_CACHE, key=lambda k: _UNPROCESSED_L1_CACHE[k][0])
        del _UNPROCESSED_L1_CACHE[oldest_key]
    return {'success': True, **result}

@router.post('/orders/factory-summary')
def api_get_factory_order_summary(data: OrderIdsRequest, db: Session=Depends(get_db), _user=Depends(require_permission('product_manage'))):
    try:
        result = svc.get_factory_order_summary(db, data.ids)
        return {'success': True, **result}
    except (OperationalError, DisconnectionError, ValueError, RuntimeError) as e:
        logger.exception(f'获取工厂订单汇总失败: {str(e)}')
        raise HTTPException(status_code=500, detail='操作失败，请稍后重试') from e

@router.post('/orders/generate-factory')
async def api_generate_factory_order(data: dict, _user=Depends(require_permission('product_manage'))):
    return {'success': True, 'message': '工厂内部采购订单生成成功（演示版本）'}

@router.post('/orders/factory-summary/save')
def api_save_factory_summary_edits(data: FactorySummarySaveRequest, db: Session=Depends(get_db), _user=Depends(require_permission('product_manage'))):
    try:
        result = svc.save_factory_summary_edits(db, data.edits)
        return {'success': True, **result}
    except (SQLAlchemyError, RuntimeError) as e:
        db.rollback()
        logger.exception(f'保存工厂订单编辑失败: {str(e)}')
        raise HTTPException(status_code=500, detail='操作失败，请稍后重试') from e

@router.post('/orders/supplier-summary')
def api_get_supplier_order_summary(data: OrderIdsRequest, db: Session=Depends(get_db), _user=Depends(require_permission('product_manage'))):
    try:
        result = svc.get_supplier_order_summary(db, data.ids)
        return {'success': True, **result}
    except (OperationalError, DisconnectionError, ValueError, RuntimeError) as e:
        logger.exception(f'获取供应商订单汇总失败: {str(e)}')
        raise HTTPException(status_code=500, detail='操作失败，请稍后重试') from e

@router.post('/orders/supplier-summary-by-vendor')
def api_get_supplier_summary_by_vendor(data: OrderIdsRequest, db: Session=Depends(get_db), _user=Depends(require_permission('product_manage'))):
    """按供应商维度汇总采购订单"""
    try:
        sorted_suppliers = svc.query_supplier_groups(db, data.ids)
        return {'success': True, 'suppliers': sorted_suppliers, 'supplier_count': len(sorted_suppliers), 'order_count': len(data.ids)}
    except (OperationalError, DisconnectionError, ValueError, RuntimeError) as e:
        logger.exception(f'按供应商汇总失败: {str(e)}')
        raise HTTPException(status_code=500, detail='操作失败，请稍后重试') from e

@router.post('/orders/generate-supplier')
async def api_generate_supplier_order(data: dict, _user=Depends(require_permission('product_manage'))):
    return {'success': True, 'message': '供应商采购订单生成成功（演示版本）'}
