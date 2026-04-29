"""
采购中心 — 供应商相关路由
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError, OperationalError, DisconnectionError

from fastapi_app.core.database import get_sync_db as get_db
from fastapi_app.core.deps import require_permission
from fastapi_app.core.logger import logger
from fastapi_app.services import purchase_center_service as svc
from fastapi_app.api.v1.endpoints.purchase_center.schemas import (
    SupplierCreateRequest, SupplierUpdateRequest,
)

router = APIRouter()


@router.get("/suppliers")
def api_get_suppliers(
    with_stats: str = Query('0'),
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    try:
        suppliers = svc.get_suppliers(db, with_stats=(with_stats == '1'))
        return {'success': True, 'suppliers': suppliers}
    except (OperationalError, DisconnectionError, ValueError) as e:
        logger.exception(f"获取供应商列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail="操作失败，请稍后重试")


@router.post("/suppliers")
def api_create_supplier(
    data: SupplierCreateRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    try:
        result = svc.create_supplier(db, data.model_dump())
        return {'success': True, 'supplier': result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (SQLAlchemyError, RuntimeError):
        db.rollback()
        raise HTTPException(status_code=500, detail="操作失败，请稍后重试")


@router.put("/suppliers/{supplier_id}")
def api_update_supplier(
    supplier_id: int,
    data: SupplierUpdateRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    try:
        result = svc.update_supplier(db, supplier_id, data.model_dump())
        return {'success': True, 'supplier': result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (SQLAlchemyError, RuntimeError):
        db.rollback()
        raise HTTPException(status_code=500, detail="操作失败，请稍后重试")


@router.get("/suppliers/{supplier_id}/materials")
def api_get_supplier_materials(
    supplier_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    try:
        materials = svc.get_supplier_materials(db, supplier_id)
        return {'success': True, 'materials': materials}
    except (OperationalError, DisconnectionError, ValueError) as e:
        logger.exception(f"获取供应商物料失败: {str(e)}")
        raise HTTPException(status_code=500, detail="操作失败，请稍后重试")
