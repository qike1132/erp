"""
库存管理 API 端点

从 Flask stock.py 迁移的 REST API。
包含入库、出库和库存查看功能。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db
from fastapi_app.core.deps import require_permission
from fastapi_app.shared_models import User, StockIn, StockOut
from fastapi_app.schemas.stock import (
    StockInCreate, StockInUpdate, StockOutCreate, StockOutUpdate,
    StockListResponse, StockActionResponse, InventoryResponse,
)
from fastapi_app.services import stock_service

router = APIRouter()


# ==================== 入库管理 ====================

@router.get("/in/list", response_model=StockListResponse)
async def list_stockins(
    page: int = Query(1, ge=1, description="页码"),
    per_page: int = Query(50, ge=1, le=5000, description="每页数量"),
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission("stockin_manage")),
):
    """入库列表（支持分页）"""
    result = await stock_service.get_stockins(db, page=page, per_page=per_page)
    return StockListResponse(data=result['items'], total=result['total'],
                             page=result['page'], per_page=result['per_page'])


@router.post("/in/create", response_model=StockActionResponse)
async def create_stockin(
    data: StockInCreate,
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission("stockin_manage")),
):
    """添加入库"""
    try:
        await stock_service.create_stockin(
            db, product_id=data.product_id, quantity=data.quantity,
            customer=data.customer, stockin_date_str=data.stockin_date,
            note=data.note or ''
        )
        return StockActionResponse(success=True, message="入库添加成功！")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/in/edit/{stockin_id}", response_model=StockActionResponse)
async def edit_stockin(
    stockin_id: int,
    data: StockInUpdate,
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission("stockin_manage")),
):
    """编辑入库记录"""
    try:
        # 获取当前记录填充未提供字段
        stockin = await db.get(StockIn, stockin_id)
        if not stockin:
            raise HTTPException(status_code=404, detail="入库记录不存在")

        quantity = data.quantity if data.quantity is not None else stockin.quantity
        customer = data.customer if data.customer is not None else stockin.customer
        stockin_date = data.stockin_date if data.stockin_date else stockin.stockin_date.strftime('%Y-%m-%d') if stockin.stockin_date else ''
        note = data.note if data.note is not None else (stockin.note or '')

        await stock_service.update_stockin(
            db, stockin_id=stockin_id, quantity=quantity,
            customer=customer, stockin_date_str=stockin_date, note=note
        )
        return StockActionResponse(success=True, message="入库编辑成功！")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/in/delete/{stockin_id}", response_model=StockActionResponse)
async def delete_stockin(
    stockin_id: int,
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission("stockin_manage")),
):
    """删除入库记录"""
    try:
        await stock_service.delete_stockin(db, stockin_id)
        return StockActionResponse(success=True, message="入库删除成功！")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== 出库管理 ====================

@router.get("/out/list", response_model=StockListResponse)
async def list_stockouts(
    page: int = Query(1, ge=1, description="页码"),
    per_page: int = Query(50, ge=1, le=5000, description="每页数量"),
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission("stockout_manage")),
):
    """出库列表（仅独立出库，支持分页）"""
    result = await stock_service.get_stockouts(db, page=page, per_page=per_page)
    return StockListResponse(data=result['items'], total=result['total'],
                             page=result['page'], per_page=result['per_page'])


@router.post("/out/create", response_model=StockActionResponse)
async def create_stockout(
    data: StockOutCreate,
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission("stockout_manage")),
):
    """添加出库"""
    try:
        await stock_service.create_stockout(
            db, product_id=data.product_id, quantity=data.quantity,
            customer=data.customer, stockout_date_str=data.stockout_date,
            note=data.note or '', order_type=data.order_type,
            country=data.country
        )
        return StockActionResponse(success=True, message="出库添加成功！")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/out/edit/{stockout_id}", response_model=StockActionResponse)
async def edit_stockout(
    stockout_id: int,
    data: StockOutUpdate,
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission("stockout_manage")),
):
    """编辑出库记录"""
    try:
        stockout = await db.get(StockOut, stockout_id)
        if not stockout:
            raise HTTPException(status_code=404, detail="出库记录不存在")

        quantity = data.quantity if data.quantity is not None else stockout.quantity
        customer = data.customer if data.customer is not None else (stockout.customer or '')
        stockout_date = data.stockout_date if data.stockout_date else stockout.stockout_date.strftime('%Y-%m-%d') if stockout.stockout_date else ''
        note = data.note if data.note is not None else (stockout.note or '')

        await stock_service.update_stockout(
            db, stockout_id=stockout_id, new_quantity=quantity,
            customer=customer, stockout_date_str=stockout_date, note=note
        )
        return StockActionResponse(success=True, message="出库编辑成功！")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/out/delete/{stockout_id}", response_model=StockActionResponse)
async def delete_stockout(
    stockout_id: int,
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission("stockout_manage")),
):
    """删除出库记录"""
    try:
        await stock_service.delete_stockout(db, stockout_id)
        return StockActionResponse(success=True, message="出库删除成功！")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== 库存查看 ====================

@router.get("/inventory", response_model=InventoryResponse)
async def inventory(
    customer: str = Query("", description="客户名称筛选"),
    product: str = Query("", description="产品名称筛选"),
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission("stockin_manage")),
):
    """库存查看（带缓存）"""
    import json
    try:
        from utils.redis_cache import redis_cache as redis_client
    except Exception:
        redis_client = None
    
    cache_key = f"inventory:overview:{customer}:{product}"
    try:
        if redis_client:
            cached_data = await redis_client.get(cache_key)
            if cached_data:
                result = json.loads(cached_data)
                return InventoryResponse(
                    data=result['inventory_data'],
                    total_order_quantity=result['total_order_qty'],
                    total_stockin_quantity=result['total_stockin_qty'],
                    total_stock=result['total_stock'],
                    all_countries=result['all_countries'],
                )
    except Exception:
        pass
    
    result = await stock_service.get_inventory(db, search_customer=customer, search_product=product)
    
    try:
        if redis_client:
            await redis_client.set(cache_key, json.dumps(result, ensure_ascii=False, default=str), ex=30)
    except Exception:
        pass
    
    return InventoryResponse(
        data=result['inventory_data'],
        total_order_quantity=result['total_order_qty'],
        total_stockin_quantity=result['total_stockin_qty'],
        total_stock=result['total_stock'],
        all_countries=result['all_countries'],
    )


@router.get("/export-inventory")
async def export_inventory(
    customer: str = Query("", description="客户名称筛选"),
    product: str = Query("", description="产品名称筛选"),
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission("stockin_manage")),
):
    """导出库存数据为 Excel 文件"""
    import io
    from fastapi.responses import StreamingResponse

    # 复用 stock_service.get_inventory 获取数据，避免重复逻辑和 Flask 实例创建
    result = await stock_service.get_inventory(db, search_customer=customer, search_product=product)
    inventory_data = result['inventory_data']

    if len(inventory_data) > 10000:
        raise HTTPException(status_code=400, detail=f"数据量过大({len(inventory_data)}条)，请缩小查询范围后重试")

    def _generate_excel():
        from utils.report_exporter import ReportExporter, generate_filename
        from urllib.parse import quote
        stats = {
            'total_count': len(inventory_data),
            'total_order_quantity': result['total_order_qty'],
            'total_stockin_quantity': result['total_stockin_qty'],
            'total_stock': result['total_stock'],
            'all_countries': result['all_countries'],
        }
        exporter = ReportExporter()
        excel_data = exporter.export_inventory_data(inventory_data, stats)
        filename = generate_filename('inventory')
        return excel_data, filename

    import asyncio
    loop = asyncio.get_running_loop()
    excel_data, filename = await loop.run_in_executor(None, _generate_excel)

    buffer = io.BytesIO(excel_data)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
    )
