"""
生产计划模块 API 端点

提供手工部录入、包装部录入、汇总动态报表等功能。
"""
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.exc import DisconnectionError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.config import settings
from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_permission
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.schemas.production_summary import (
    CraftWorkActionResponse,
    CraftWorkCreate,
    CraftWorkListResponse,
    CraftWorkUpdate,
    PackagingRecordActionResponse,
    PackagingRecordCreate,
    PackagingRecordListResponse,
    PackagingRecordUpdate,
    PackagingUploadResponse,
    ProductionSummaryResponse,
)
from fastapi_app.services import production_summary_service
from fastapi_app.shared_models import User

router = APIRouter()

@router.get('/craft/list', response_model=CraftWorkListResponse)
async def list_craft_works(year: int=Query(..., description='年份'), month: int=Query(..., ge=1, le=12, description='月份'), work_date: str=Query('', description='指定日期筛选 (YYYY-MM-DD)'), db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('production_summary_view'))):
    """手工部生产记录列表（含按日汇总和皮套出库数据）"""
    try:
        result = await production_summary_service.get_craft_works(db, year, month, work_date)
        return CraftWorkListResponse(data=result['data'], daily_summary=result['daily_summary'], total=result['total'])
    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(status_code=500, detail=f'获取手工部数据失败: {settings.sanitize_error(e)}') from e

@router.post('/craft/create', response_model=CraftWorkActionResponse)
async def create_craft_work(data: CraftWorkCreate, db: AsyncSession=Depends(get_async_db), user: User=Depends(require_permission('production_summary_manage'))):
    """创建手工部生产记录"""
    async with db_transaction(db):
        await production_summary_service.create_craft_work(db, worker_name=data.worker_name, quantity=data.quantity, work_date_str=data.work_date, remark=data.remark or '', created_by=user.username if hasattr(user, 'username') else '')
    return CraftWorkActionResponse(success=True, message='手工部记录创建成功！')

@router.put('/craft/edit/{record_id}', response_model=CraftWorkActionResponse)
async def update_craft_work(record_id: int, data: CraftWorkUpdate, db: AsyncSession=Depends(get_async_db), user: User=Depends(require_permission('production_summary_manage'))):
    """编辑手工部生产记录"""
    async with db_transaction(db):
        update_data = data.model_dump(exclude_unset=True)
        await production_summary_service.update_craft_work(db, record_id, created_by=user.username if hasattr(user, 'username') else '', **update_data)
    return CraftWorkActionResponse(success=True, message='手工部记录更新成功！')

@router.delete('/craft/delete/{record_id}', response_model=CraftWorkActionResponse)
async def delete_craft_work(record_id: int, db: AsyncSession=Depends(get_async_db), _user: User=Depends(require_permission('production_summary_manage'))):
    """删除手工部生产记录"""
    async with db_transaction(db):
        await production_summary_service.delete_craft_work(db, record_id)
    return CraftWorkActionResponse(success=True, message='手工部记录删除成功！')

@router.get('/craft/export')
async def export_craft_works(start_date: str=Query('', description='起始日期 (YYYY-MM-DD)'), end_date: str=Query('', description='结束日期 (YYYY-MM-DD)'), db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('production_summary_view'))):
    """导出手工部生产数据为Excel"""
    try:
        content = await production_summary_service.export_craft_works(db, start_date=start_date, end_date=end_date)
        return Response(content=content, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': 'attachment; filename=craft_work_export.xlsx'})
    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(status_code=500, detail=f'导出失败: {settings.sanitize_error(e)}') from e

@router.get('/packaging/list', response_model=PackagingRecordListResponse)
async def list_packaging_records(year: int=Query(..., description='年份'), month: int=Query(..., ge=1, le=12, description='月份'), customer: str=Query('', description='客户名称筛选'), start_date: str=Query('', description='起始日期 (YYYY-MM-DD)'), end_date: str=Query('', description='结束日期 (YYYY-MM-DD)'), db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('production_summary_view'))):
    """包装部记录列表"""
    try:
        result = await production_summary_service.get_packaging_records(db, year, month, customer=customer, start_date=start_date, end_date=end_date)
        return PackagingRecordListResponse(data=result['data'], total=result['total'])
    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(status_code=500, detail=f'获取包装部数据失败: {settings.sanitize_error(e)}') from e

@router.post('/packaging/create', response_model=PackagingRecordActionResponse)
async def create_packaging_record(data: PackagingRecordCreate, db: AsyncSession=Depends(get_async_db), user: User=Depends(require_permission('production_summary_manage'))):
    """创建包装部记录"""
    async with db_transaction(db):
        await production_summary_service.create_packaging_record(db, customer=data.customer, product_name=data.product_name, barcode=data.barcode, quantity=data.quantity, pack_date_str=data.pack_date, remark=data.remark or '', created_by=user.username if hasattr(user, 'username') else '')
    return PackagingRecordActionResponse(success=True, message='包装部记录创建成功！')

@router.put('/packaging/edit/{record_id}', response_model=PackagingRecordActionResponse)
async def update_packaging_record(record_id: int, data: PackagingRecordUpdate, db: AsyncSession=Depends(get_async_db), user: User=Depends(require_permission('production_summary_manage'))):
    """编辑包装部记录"""
    async with db_transaction(db):
        update_data = data.model_dump(exclude_unset=True)
        await production_summary_service.update_packaging_record(db, record_id, created_by=user.username if hasattr(user, 'username') else '', **update_data)
    return PackagingRecordActionResponse(success=True, message='包装部记录更新成功！')

@router.delete('/packaging/delete/{record_id}', response_model=PackagingRecordActionResponse)
async def delete_packaging_record(record_id: int, db: AsyncSession=Depends(get_async_db), _user: User=Depends(require_permission('production_summary_manage'))):
    """删除包装部记录"""
    async with db_transaction(db):
        await production_summary_service.delete_packaging_record(db, record_id)
    return PackagingRecordActionResponse(success=True, message='包装部记录删除成功！')

@router.post('/packaging/upload', response_model=PackagingUploadResponse)
async def upload_packaging_excel(file: UploadFile=File(..., description='Excel文件'), db: AsyncSession=Depends(get_async_db), user: User=Depends(require_permission('production_summary_manage'))):
    """批量导入包装部记录（Excel上传）"""
    if not file.filename.endswith('.xlsx'):
        raise HTTPException(status_code=400, detail='仅支持 .xlsx 格式文件，.xls 已不再支持')
    try:
        content = await file.read()
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f'文件读取失败: {e}') from e
    async with db_transaction(db):
        created_by = user.username if hasattr(user, 'username') else ''
        result = await production_summary_service.upload_packaging_excel(db, content, created_by)
    return {'success': True, **result}

@router.get('/packaging/export')
async def export_packaging_records(start_date: str=Query('', description='起始日期 (YYYY-MM-DD)'), end_date: str=Query('', description='结束日期 (YYYY-MM-DD)'), db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('production_summary_view'))):
    """导出包装部数据为Excel"""
    try:
        content = await production_summary_service.export_packaging_records(db, start_date=start_date, end_date=end_date)
        return Response(content=content, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': 'attachment; filename=packaging_export.xlsx'})
    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(status_code=500, detail=f'导出失败: {settings.sanitize_error(e)}') from e

@router.get('/summary', response_model=ProductionSummaryResponse)
async def production_summary(year: int=Query(..., description='年份'), month: int=Query(..., ge=1, le=12, description='月份'), db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('production_summary_view'))):
    """汇总动态报表：按日展示皮套出库→手工部生产→包装部进仓"""
    try:
        result = await production_summary_service.get_production_summary(db, year, month)
        return ProductionSummaryResponse(data=result['data'], monthly_summary=result['monthly_summary'], total=result['total'])
    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(status_code=500, detail=f'获取汇总报表失败: {settings.sanitize_error(e)}') from e
