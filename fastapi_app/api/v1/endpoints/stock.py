"""
库存管理 API 端点

从 Flask stock.py 迁移的 REST API。
包含入库、出库和库存查看功能。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db
from fastapi_app.core.deps import require_permission
from fastapi_app.shared_models import User
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
    return StockListResponse(data=result['items'], total=result['total'])


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
        from fastapi_app.shared_models import StockIn
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
    return StockListResponse(data=result['items'], total=result['total'])


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
            note=data.note or ''
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
        from fastapi_app.shared_models import StockOut
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
    """库存查看"""
    result = await stock_service.get_inventory(db, search_customer=customer, search_product=product)
    return InventoryResponse(
        data=result['inventory_data'],
        total_order_quantity=result['total_order_qty'],
        total_stockin_quantity=result['total_stockin_qty'],
        total_stock=result['total_stock'],
    )


@router.get("/export-inventory")
async def export_inventory(
    customer: str = Query("", description="客户名称筛选"),
    product: str = Query("", description="产品名称筛选"),
    _user: User = Depends(require_permission("stockin_manage")),
):
    """导出库存数据为 Excel 文件"""
    import asyncio
    import io
    from fastapi.responses import StreamingResponse

    def _sync_export():
        from app import create_app, db as flask_db
        from app.models import Order, StockIn, Product as FlaskProduct, StockOut as FlaskStockOut
        from sqlalchemy.orm import selectinload
        from utils.report_exporter import ReportExporter, generate_filename

        app = create_app()
        with app.app_context():
            products_query = FlaskProduct.query.options(
                selectinload(FlaskProduct.orders),
                selectinload(FlaskProduct.stockins).selectinload(StockIn.stockin_stockouts)
            )

            if product:
                products_query = products_query.filter(FlaskProduct.name.like(f'%{product}%'))

            products = products_query.all()

            inventory_data = []
            total_order_qty = 0
            total_stockin_qty = 0
            total_total_qty = 0

            for p in products:
                stockins = p.stockins
                if customer:
                    stockins = [s for s in stockins if s.customer == customer]

                customers_set = set()
                for s in stockins:
                    if s.customer:
                        customers_set.add(s.customer)

                all_stockouts = FlaskStockOut.query.filter_by(
                    product_id=p.id, stockin_id=None
                ).all()
                if customer:
                    all_stockouts = [so for so in all_stockouts if so.customer == customer]

                for so in all_stockouts:
                    if so.customer:
                        customers_set.add(so.customer)

                orders = Order.query.filter_by(product_id=p.id).all()
                if customer:
                    orders = [o for o in orders if o.customer == customer]

                order_customers = set(o.customer for o in orders)
                customers_set.update(order_customers)

                for cust in customers_set:
                    cust_stockin_qty = sum(
                        s.quantity - sum(so.quantity for so in s.stockin_stockouts)
                        for s in p.stockins if s.customer == cust
                    )

                    cust_stockout_qty = sum(
                        so.quantity for so in FlaskStockOut.query.filter_by(
                            product_id=p.id, customer=cust, stockin_id=None
                        ).all()
                    )

                    customer_orders = [o for o in Order.query.filter_by(
                        product_id=p.id, customer=cust
                    ).all()]
                    cust_order_total = sum(o.quantity for o in customer_orders)

                    direct_shipped = flask_db.session.query(
                        flask_db.func.sum(FlaskStockOut.quantity)
                    ).filter(
                        FlaskStockOut.product_id == p.id,
                        FlaskStockOut.customer == cust,
                        FlaskStockOut.stockin_id.is_(None),
                        FlaskStockOut.order_id.is_(None)
                    ).scalar() or 0

                    order_shipped = flask_db.session.query(
                        flask_db.func.sum(FlaskStockOut.quantity)
                    ).filter(
                        FlaskStockOut.product_id == p.id,
                        FlaskStockOut.customer == cust,
                        FlaskStockOut.stockin_id.is_(None),
                        FlaskStockOut.order_id.isnot(None)
                    ).scalar() or 0

                    total_shipped = direct_shipped + order_shipped
                    available_order_qty = max(0, cust_order_total - total_shipped)
                    total_stock = max(0, cust_stockin_qty + available_order_qty)

                    has_stockin_record = any(s.customer == cust for s in p.stockins)
                    has_order_record = len(customer_orders) > 0
                    has_positive_stock = (available_order_qty > 0 or
                                           cust_stockin_qty > 0 or
                                           total_stock > 0)

                    if (has_stockin_record or has_order_record) and has_positive_stock:
                        inventory_data.append({
                            'customer': cust,
                            'product_name': p.name,
                            'product_barcode': p.barcode or '',
                            'order_quantity': available_order_qty if available_order_qty > 0 else '',
                            'stockin_quantity': cust_stockin_qty if cust_stockin_qty > 0 else '',
                            'total_stock': total_stock if total_stock > 0 else ''
                        })
                        total_stockin_qty += cust_stockin_qty
                        total_order_qty += available_order_qty
                        total_total_qty += total_stock

            if len(inventory_data) > 10000:
                return None, f"数据量过大({len(inventory_data)}条)，请缩小查询范围后重试"

            stats = {
                'total_count': len(inventory_data),
                'total_order_quantity': total_order_qty,
                'total_stockin_quantity': total_stockin_qty,
                'total_stock': total_total_qty
            }

            exporter = ReportExporter()
            excel_data = exporter.export_inventory_data(inventory_data, stats)
            filename = generate_filename('inventory')
            return excel_data, filename

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _sync_export)

    if result[0] is None:
        raise HTTPException(status_code=400, detail=result[1])

    excel_data, filename = result
    buffer = io.BytesIO(excel_data)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"}
    )
