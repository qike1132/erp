"""
采购中心 — 采购订单 CRUD 路由
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError, OperationalError, DisconnectionError

from fastapi_app.core.database import get_sync_db as get_db
from fastapi_app.core.deps import require_permission
from fastapi_app.core.logger import logger
from fastapi_app.services import purchase_center_service as svc
from fastapi_app.api.v1.endpoints.purchase_center.schemas import (
    OrderIdsRequest, OrderIdRequest, OrderIdsAltRequest,
    PurchaseOrderCreateRequest, PurchaseOrderUpdateRequest,
    OneClickGenerateRequest, BatchCompleteRequest,
    ExportCompletedRequest, FactorySummarySaveRequest,
)

router = APIRouter()


@router.post("/orders")
def api_create_purchase_order(
    data: PurchaseOrderCreateRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    try:
        result = svc.create_purchase_order(db, data.model_dump(), _user.id, _user.username)
        db.commit()
        return {'success': True, **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (SQLAlchemyError, RuntimeError) as e:
        db.rollback()
        logger.error(f"创建采购订单失败: {e}")
        raise HTTPException(status_code=500, detail="创建订单失败，请稍后重试")


@router.post("/orders/one-click-generate")
def api_one_click_generate_order(
    data: OneClickGenerateRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    try:
        result = svc.one_click_generate_order(db, data.order_ids, _user.id, _user.username)
        return {'success': True, **result}
    except (ValueError, SQLAlchemyError, RuntimeError) as e:
        db.rollback()
        logger.exception(f"一键生成采购订单失败: {str(e)}")
        raise HTTPException(status_code=500, detail="生成采购订单失败，请稍后重试")


@router.get("/orders")
def api_get_purchase_orders(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1),
    status: str = Query('', max_length=50),
    customer: str = Query('', max_length=100),
    product_name: str = Query('', max_length=100),
    start_date: str = Query('', max_length=20),
    end_date: str = Query('', max_length=20),
    order_no: str = Query('', max_length=50),
    supplier: str = Query('', max_length=100),
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    result = svc.get_purchase_orders(
        db, page=page, per_page=per_page, status=status,
        customer=customer, product_name=product_name,
        start_date=start_date, end_date=end_date,
        order_no=order_no, supplier=supplier,
    )
    return {'success': True, **result}


# 已完成订单相关路由（必须在 /api/orders/{order_id} 之前，避免路径冲突）

@router.get("/orders/completed")
def api_get_completed_purchase_orders(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1),
    order_no: str = Query('', max_length=50),
    customer_name: str = Query('', max_length=100),
    product_name: str = Query('', max_length=100),
    supplier_name: str = Query('', max_length=100),
    barcode: str = Query('', max_length=50),
    material_name: str = Query('', max_length=100),
    start_date: str = Query('', max_length=20),
    end_date: str = Query('', max_length=20),
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    result = svc.get_completed_purchase_orders(
        db, page=page, per_page=per_page, order_no=order_no,
        customer_name=customer_name, product_name=product_name,
        supplier_name=supplier_name, barcode=barcode,
        material_name=material_name,
        start_date=start_date, end_date=end_date,
    )
    return {'success': True, **result}


@router.post("/orders/completed/export")
def api_export_completed_orders(
    data: ExportCompletedRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    html = svc.export_completed_orders(db, data.model_dump(exclude_none=True))
    return {'success': True, 'html': html}


@router.get("/orders/completed/suggestions")
def api_get_completed_order_suggestions(
    field: str = Query(''),
    q: str = Query(''),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    suggestions = svc.get_completed_order_suggestions(db, field, q, limit)
    return {'success': True, 'suggestions': suggestions}


@router.get("/orders/completed/quick-filters")
async def api_get_completed_order_quick_filters(
    _user=Depends(require_permission("product_manage")),
):
    quick_filters = svc.get_completed_order_quick_filters()
    return {'success': True, 'quick_filters': quick_filters}


@router.get("/orders/{order_id}")
def api_get_purchase_order(
    order_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    result = svc.get_purchase_order(db, order_id)
    if not result:
        raise HTTPException(status_code=404, detail="订单不存在")
    return {'success': True, 'order': result}


@router.put("/orders/{order_id}")
def api_update_purchase_order(
    order_id: int,
    data: PurchaseOrderUpdateRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    result = svc.update_purchase_order(db, order_id, data.model_dump(exclude_unset=True), _user.username)
    if not result:
        raise HTTPException(status_code=404, detail="订单不存在")
    return {'success': True, 'order': result}


@router.delete("/orders/{order_id}")
def api_delete_purchase_order(
    order_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    result = svc.delete_purchase_order(db, order_id)
    if not result:
        raise HTTPException(status_code=404, detail="订单不存在")
    return {'success': True, 'message': result}


@router.post("/orders/complete")
def api_complete_purchase_order(
    data: OrderIdRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    try:
        result = svc.complete_purchase_order(db, data.order_id, _user.id, _user.username)
        return {'success': True, **result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (SQLAlchemyError, RuntimeError) as e:
        db.rollback()
        logger.error(f"完成订单失败: {e}")
        raise HTTPException(status_code=500, detail="完成订单失败，请稍后重试")


@router.post("/orders/batch-complete")
def api_batch_complete_purchase_orders(
    data: BatchCompleteRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    try:
        result = svc.batch_complete_purchase_orders(db, data.ids, _user.id, _user.username)
        return {'success': True, **result}
    except (ValueError, SQLAlchemyError, RuntimeError) as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="完成订单失败，请稍后重试")


@router.post("/orders/batch-delete")
def api_batch_delete_purchase_orders(
    data: OrderIdsAltRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    """批量删除采购订单"""
    try:
        result = svc.batch_delete_purchase_orders(db, data.order_ids)
        return {'success': True, **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/orders/{order_id}/print")
def api_get_order_print_data(
    order_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    result = svc.get_purchase_order(db, order_id)
    if not result:
        raise HTTPException(status_code=404, detail="订单不存在")
    return {'success': True, 'order': result}


@router.post("/orders/batch-print")
def api_get_orders_batch_print_data(
    data: OrderIdsRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    from fastapi_app.shared_models import PurchaseOrder
    orders = db.query(PurchaseOrder).filter(PurchaseOrder.id.in_(data.ids)).all()
    return {'success': True, 'orders': [o.to_dict() for o in orders]}


@router.get("/unprocessed-orders")
def api_get_unprocessed_orders(
    customer: str = Query(''),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1),
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    result = svc.get_unprocessed_orders(db, customer=customer, page=page, per_page=per_page)
    return {'success': True, **result}


@router.post("/orders/factory-summary")
def api_get_factory_order_summary(
    data: OrderIdsRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    try:
        result = svc.get_factory_order_summary(db, data.ids)
        return {'success': True, **result}
    except (OperationalError, DisconnectionError, ValueError, RuntimeError) as e:
        logger.exception(f"获取工厂订单汇总失败: {str(e)}")
        raise HTTPException(status_code=500, detail="操作失败，请稍后重试")


@router.post("/orders/generate-factory")
async def api_generate_factory_order(
    data: dict,
    _user=Depends(require_permission("product_manage")),
):
    return {'success': True, 'message': '工厂内部采购订单生成成功（演示版本）'}


@router.post("/orders/factory-summary/save")
def api_save_factory_summary_edits(
    data: FactorySummarySaveRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    try:
        result = svc.save_factory_summary_edits(db, data.edits)
        return {'success': True, **result}
    except (SQLAlchemyError, RuntimeError) as e:
        db.rollback()
        logger.exception(f"保存工厂订单编辑失败: {str(e)}")
        raise HTTPException(status_code=500, detail="操作失败，请稍后重试")


@router.post("/orders/supplier-summary")
def api_get_supplier_order_summary(
    data: OrderIdsRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    try:
        result = svc.get_supplier_order_summary(db, data.ids)
        return {'success': True, **result}
    except (OperationalError, DisconnectionError, ValueError, RuntimeError) as e:
        logger.exception(f"获取供应商订单汇总失败: {str(e)}")
        raise HTTPException(status_code=500, detail="操作失败，请稍后重试")


@router.post("/orders/supplier-summary-by-vendor")
def api_get_supplier_summary_by_vendor(
    data: OrderIdsRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    """按供应商维度汇总采购订单"""
    try:
        sorted_suppliers = svc.query_supplier_groups(db, data.ids)
        return {
            'success': True,
            'suppliers': sorted_suppliers,
            'supplier_count': len(sorted_suppliers),
            'order_count': len(data.ids),
        }
    except (OperationalError, DisconnectionError, ValueError, RuntimeError) as e:
        logger.exception(f"按供应商汇总失败: {str(e)}")
        raise HTTPException(status_code=500, detail="操作失败，请稍后重试")


@router.post("/orders/generate-supplier")
async def api_generate_supplier_order(
    data: dict,
    _user=Depends(require_permission("product_manage")),
):
    return {'success': True, 'message': '供应商采购订单生成成功（演示版本）'}
