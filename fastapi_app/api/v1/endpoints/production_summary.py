"""
生产计划模块 API 端点

提供手工部录入、包装部录入、汇总动态报表等功能。

职责：
- 提供手工部生产记录的增删改查和导出接口
- 提供包装部生产记录的增删改查、Excel 批量导入和导出接口
- 提供汇总动态报表接口（按日展示皮套出库→手工部生产→包装部进仓）
"""
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.exc import DisconnectionError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.backup_progress import _sanitize_error
from fastapi_app.core.config import settings
from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_permission
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.core.response import success_response
from fastapi_app.core.validators import require_upload_magic
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

#: 包装部 Excel 上传体积上限（端点级兜底，**文件级**口径）。multipart 请求体 =
#: 文件 + 边界/字段头开销，外层 body 预算由 core/middleware.py 的放宽名单给足
#: 余量、nginx 同步 12m——本常量若与外层相等，「恰好 10MB 的合法文件」会在
#: 抵达端点前被 413（M2，2026-10-25 上线前检查）。
MAX_PACKAGING_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB


@router.get('/craft/list', response_model=CraftWorkListResponse)
async def list_craft_works(
    year: int = Query(..., description='年份'),
    month: int = Query(..., ge=1, le=12, description='月份'),
    work_date: str = Query('', description='指定日期筛选 (YYYY-MM-DD)'),
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission('production_summary_view')),
) -> CraftWorkListResponse:
    """手工部生产记录列表（含按日汇总和皮套出库数据）。

    Args:
        year: 年份。
        month: 月份，1-12。
        work_date: 指定日期筛选（YYYY-MM-DD）。
        db: 异步数据库会话（只读副本）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        CraftWorkListResponse: 包含手工部记录列表、按日汇总和总数的响应。

    Raises:
        HTTPException: 数据库连接异常时抛出 500。
    """
    try:
        result = await production_summary_service.get_craft_works(db, year, month, work_date)
        return CraftWorkListResponse(
            data=result['data'], daily_summary=result['daily_summary'], total=result['total'],
        )
    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(status_code=500, detail=f'获取手工部数据失败: {settings.sanitize_error(e)}') from e


@router.post('/craft/create', response_model=CraftWorkActionResponse)
async def create_craft_work(
    data: CraftWorkCreate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission('production_summary_manage')),
) -> CraftWorkActionResponse:
    """创建手工部生产记录。

    Args:
        data: 手工部记录创建参数（工人、数量、日期等）。
        db: 异步数据库会话（读写主库）。
        user: 当前登录用户，作为记录创建人。

    Returns:
        CraftWorkActionResponse: 包含成功标志和提示消息的响应。
    """
    async with db_transaction(db):
        await production_summary_service.create_craft_work(
            db, worker_name=data.worker_name, quantity=data.quantity,
            work_date_str=data.work_date, remark=data.remark or '',
            created_by=user.username if hasattr(user, 'username') else '',
        )
    return CraftWorkActionResponse(success=True, message='手工部记录创建成功！')


@router.put('/craft/edit/{record_id}', response_model=CraftWorkActionResponse)
async def update_craft_work(
    record_id: int,
    data: CraftWorkUpdate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission('production_summary_manage')),
) -> CraftWorkActionResponse:
    """编辑手工部生产记录。

    Args:
        record_id: 手工部记录 ID。
        data: 手工部记录更新参数（仅包含需要修改的字段）。
        db: 异步数据库会话（读写主库）。
        user: 当前登录用户，作为操作人。

    Returns:
        CraftWorkActionResponse: 包含成功标志和提示消息的响应。
    """
    async with db_transaction(db):
        update_data = data.model_dump(exclude_unset=True)
        await production_summary_service.update_craft_work(
            db, record_id, created_by=user.username if hasattr(user, 'username') else '', **update_data,
        )
    return CraftWorkActionResponse(success=True, message='手工部记录更新成功！')


@router.delete('/craft/delete/{record_id}', response_model=CraftWorkActionResponse)
async def delete_craft_work(
    record_id: int,
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission('production_summary_manage')),
) -> CraftWorkActionResponse:
    """删除手工部生产记录。

    Args:
        record_id: 手工部记录 ID。
        db: 异步数据库会话（读写主库）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        CraftWorkActionResponse: 包含成功标志和提示消息的响应。
    """
    async with db_transaction(db):
        await production_summary_service.delete_craft_work(db, record_id)
    return CraftWorkActionResponse(success=True, message='手工部记录删除成功！')


@router.get('/craft/export')
async def export_craft_works(
    start_date: str = Query('', description='起始日期 (YYYY-MM-DD)'),
    end_date: str = Query('', description='结束日期 (YYYY-MM-DD)'),
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission('production_summary_view')),
) -> Response:
    """导出手工部生产数据为Excel。

    Args:
        start_date: 起始日期（YYYY-MM-DD）。
        end_date: 结束日期（YYYY-MM-DD）。
        db: 异步数据库会话（只读副本）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        Response: Excel 文件流响应。

    Raises:
        HTTPException: 数据库连接异常时抛出 500。
    """
    try:
        content = await production_summary_service.export_craft_works(
            db, start_date=start_date, end_date=end_date,
        )
        return Response(
            content=content,
            media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={'Content-Disposition': 'attachment; filename=craft_work_export.xlsx'},
        )
    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(status_code=500, detail=f'导出失败: {settings.sanitize_error(e)}') from e


@router.get('/packaging/list', response_model=PackagingRecordListResponse)
async def list_packaging_records(
    year: int = Query(..., description='年份'),
    month: int = Query(..., ge=1, le=12, description='月份'),
    customer: str = Query('', description='客户名称筛选'),
    start_date: str = Query('', description='起始日期 (YYYY-MM-DD)'),
    end_date: str = Query('', description='结束日期 (YYYY-MM-DD)'),
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission('production_summary_view')),
) -> PackagingRecordListResponse:
    """包装部记录列表（支持按年月、客户、日期范围筛选）。

    Args:
        year: 年份。
        month: 月份，1-12。
        customer: 客户名称筛选关键字。
        start_date: 起始日期（YYYY-MM-DD）。
        end_date: 结束日期（YYYY-MM-DD）。
        db: 异步数据库会话（只读副本）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        PackagingRecordListResponse: 包含包装部记录列表和总数的响应。

    Raises:
        HTTPException: 数据库连接异常时抛出 500。
    """
    try:
        result = await production_summary_service.get_packaging_records(
            db, year, month, customer=customer, start_date=start_date, end_date=end_date,
        )
        return PackagingRecordListResponse(data=result['data'], total=result['total'])
    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(status_code=500, detail=f'获取包装部数据失败: {settings.sanitize_error(e)}') from e


@router.post('/packaging/create', response_model=PackagingRecordActionResponse)
async def create_packaging_record(
    data: PackagingRecordCreate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission('production_summary_manage')),
) -> PackagingRecordActionResponse:
    """创建包装部记录。

    Args:
        data: 包装部记录创建参数（客户、产品、条码、数量、日期等）。
        db: 异步数据库会话（读写主库）。
        user: 当前登录用户，作为记录创建人。

    Returns:
        PackagingRecordActionResponse: 包含成功标志和提示消息的响应。
    """
    async with db_transaction(db):
        await production_summary_service.create_packaging_record(
            db, customer=data.customer, product_name=data.product_name, barcode=data.barcode,
            quantity=data.quantity, pack_date_str=data.pack_date, remark=data.remark or '',
            created_by=user.username if hasattr(user, 'username') else '',
        )
    return PackagingRecordActionResponse(success=True, message='包装部记录创建成功！')


@router.put('/packaging/edit/{record_id}', response_model=PackagingRecordActionResponse)
async def update_packaging_record(
    record_id: int,
    data: PackagingRecordUpdate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission('production_summary_manage')),
) -> PackagingRecordActionResponse:
    """编辑包装部记录。

    Args:
        record_id: 包装部记录 ID。
        data: 包装部记录更新参数（仅包含需要修改的字段）。
        db: 异步数据库会话（读写主库）。
        user: 当前登录用户，作为操作人。

    Returns:
        PackagingRecordActionResponse: 包含成功标志和提示消息的响应。
    """
    async with db_transaction(db):
        update_data = data.model_dump(exclude_unset=True)
        await production_summary_service.update_packaging_record(
            db, record_id, created_by=user.username if hasattr(user, 'username') else '', **update_data,
        )
    return PackagingRecordActionResponse(success=True, message='包装部记录更新成功！')


@router.delete('/packaging/delete/{record_id}', response_model=PackagingRecordActionResponse)
async def delete_packaging_record(
    record_id: int,
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission('production_summary_manage')),
) -> PackagingRecordActionResponse:
    """删除包装部记录。

    Args:
        record_id: 包装部记录 ID。
        db: 异步数据库会话（读写主库）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        PackagingRecordActionResponse: 包含成功标志和提示消息的响应。
    """
    async with db_transaction(db):
        await production_summary_service.delete_packaging_record(db, record_id)
    return PackagingRecordActionResponse(success=True, message='包装部记录删除成功！')


@router.post('/packaging/upload', response_model=PackagingUploadResponse)
async def upload_packaging_excel(
    file: UploadFile = File(..., description='Excel文件'),
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission('production_summary_manage')),
) -> PackagingUploadResponse:
    """批量导入包装部记录（Excel上传）。

    Args:
        file: 上传的 Excel 文件（.xlsx 格式）。
        db: 异步数据库会话（读写主库）。
        user: 当前登录用户，作为操作人。

    Returns:
        PackagingUploadResponse: 包含导入结果的响应。

    Raises:
        HTTPException: 文件格式不支持或读取失败时抛出 400。
    """
    filename = file.filename or ''
    if not filename.endswith('.xlsx'):
        raise HTTPException(status_code=400, detail='仅支持 .xlsx 格式文件，.xls 已不再支持')
    # 端点级体积兜底（文件级 10MB；multipart body 的余量由 core/middleware.py 放宽名单负责）
    declared = getattr(file, 'size', None)
    if declared is not None and declared > MAX_PACKAGING_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail=f'文件超过 {MAX_PACKAGING_UPLOAD_SIZE // 1024 // 1024}MB 上传限制')
    try:
        content = await file.read()
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=_sanitize_error(f'文件读取失败: {e}')) from e
    if len(content) > MAX_PACKAGING_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail=f'文件超过 {MAX_PACKAGING_UPLOAD_SIZE // 1024 // 1024}MB 上传限制')
    # P0-12：扩展名之外再校验文件头（改扩展名的伪 xlsx 在此拦下）
    require_upload_magic(content, ('xlsx', 'xlsm'), filename=file.filename or '')
    async with db_transaction(db):
        created_by = user.username if hasattr(user, 'username') else ''
        result = await production_summary_service.upload_packaging_excel(db, content, created_by)
    return PackagingUploadResponse(**success_response(**{**result}))


@router.get('/packaging/export')
async def export_packaging_records(
    start_date: str = Query('', description='起始日期 (YYYY-MM-DD)'),
    end_date: str = Query('', description='结束日期 (YYYY-MM-DD)'),
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission('production_summary_view')),
) -> Response:
    """导出包装部数据为Excel。

    Args:
        start_date: 起始日期（YYYY-MM-DD）。
        end_date: 结束日期（YYYY-MM-DD）。
        db: 异步数据库会话（只读副本）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        Response: Excel 文件流响应。

    Raises:
        HTTPException: 数据库连接异常时抛出 500。
    """
    try:
        content = await production_summary_service.export_packaging_records(
            db, start_date=start_date, end_date=end_date,
        )
        return Response(
            content=content,
            media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={'Content-Disposition': 'attachment; filename=packaging_export.xlsx'},
        )
    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(status_code=500, detail=f'导出失败: {settings.sanitize_error(e)}') from e


@router.get('/summary', response_model=ProductionSummaryResponse)
async def production_summary(
    year: int = Query(..., description='年份'),
    month: int = Query(..., ge=1, le=12, description='月份'),
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission('production_summary_view')),
) -> ProductionSummaryResponse:
    """汇总动态报表：按日展示皮套出库→手工部生产→包装部进仓。

    Args:
        year: 年份。
        month: 月份，1-12。
        db: 异步数据库会话（只读副本）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        ProductionSummaryResponse: 包含汇总数据和月度统计的响应。

    Raises:
        HTTPException: 数据库连接异常时抛出 500。
    """
    try:
        result = await production_summary_service.get_production_summary(db, year, month)
        return ProductionSummaryResponse(
            data=result['data'], monthly_summary=result['monthly_summary'], total=result['total'],
        )
    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(status_code=500, detail=f'获取汇总报表失败: {settings.sanitize_error(e)}') from e
