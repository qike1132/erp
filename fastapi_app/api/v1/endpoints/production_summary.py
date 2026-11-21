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

from fastapi_app.core.config import settings
from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_permission
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
from fastapi_app.services.export_limits import ExportLimitError
from fastapi_app.shared_models import User

router = APIRouter()

#: 旧表写入口（craft/packaging create）的停用说明。文案直接给出去处，
#: 让仍在调这两个接口的旧前端/脚本知道该去哪录，而不是只看到一个 410 码。
LEGACY_WRITE_GONE_DETAIL = (
    '该入口已停用，请在 /production 录入生产记录'
    '（本入口写入的是历史旧表，任何页面都不再读取它，继续写入等于数据消失）'
)


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
    """【已停用，恒返回 410】创建手工部生产记录。

    该入口写的是旧表 `craft_work`，而生产报表页面（`/production`）只读
    `daily_production_record` —— 从这里提交的记录任何页面都看不见（审计 #6）。
    保留路由与入参模型是为了让老前端的请求得到明确答复，而不是 404 或静默写入。

    Raises:
        HTTPException: 410 —— 该入口已停用，请改用 `/production` 录入。
    """
    raise HTTPException(
        status_code=410,
        detail=LEGACY_WRITE_GONE_DETAIL,
    )


@router.put('/craft/edit/{record_id}', response_model=CraftWorkActionResponse)
async def update_craft_work(
    record_id: int,
    data: CraftWorkUpdate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission('production_summary_manage')),
) -> CraftWorkActionResponse:
    """【已停用，恒返回 410】编辑手工部生产记录（审计 M-1，2026-11-21）。

    与 create 同一处置：旧表 `craft_work` 已无页面读取（生产报表页只读
    `daily_production_record`），编辑「成功」等于把改动写进黑洞。保留路由与
    入参模型是为了让老前端的请求得到明确答复，而不是 404 或静默写入。

    Raises:
        HTTPException: 410 —— 该入口已停用，请改用 `/production` 录入。
    """
    raise HTTPException(
        status_code=410,
        detail=LEGACY_WRITE_GONE_DETAIL,
    )


@router.delete('/craft/delete/{record_id}', response_model=CraftWorkActionResponse)
async def delete_craft_work(
    record_id: int,
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission('production_summary_manage')),
) -> CraftWorkActionResponse:
    """【已停用，恒返回 410】删除手工部生产记录（审计 M-1，2026-11-21）。

    与 create 同一处置：旧表 `craft_work` 已无页面读取，任何页面都看不见这条
    数据的消失，删除只是制造「看起来成功了」的假象。

    Raises:
        HTTPException: 410 —— 该入口已停用，请改用 `/production` 录入。
    """
    raise HTTPException(
        status_code=410,
        detail=LEGACY_WRITE_GONE_DETAIL,
    )


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
    except ExportLimitError as e:
        # 行数上界（审计 A-15）：服务层超限抛 ExportLimitError，映射 413 引导缩小范围，
        # 而不是像从前那样静默截断后照常 200 出一份缺行的文件。
        raise HTTPException(status_code=413, detail=str(e)) from e
    except ValueError as e:
        # 日期非法等其余 ValueError 回 400（评审 F1）——
        # L-35/N-54（2026-11-21 审计）：改为异常类型判别，不再靠 '日期' in str(e)。
        raise HTTPException(status_code=400, detail=str(e)) from e
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
    """【已停用，恒返回 410】创建包装部记录。

    与手工部 create 同一处置（审计 #6）：旧表 `packaging_record` 已无页面读取，
    写入等于让数据消失。批量导入 `/packaging/upload` 走的是同一张旧表，故一并保留
    现状但在服务层 docstring 标注了遗留原因。

    Raises:
        HTTPException: 410 —— 该入口已停用，请改用 `/production` 录入。
    """
    raise HTTPException(
        status_code=410,
        detail=LEGACY_WRITE_GONE_DETAIL,
    )


@router.put('/packaging/edit/{record_id}', response_model=PackagingRecordActionResponse)
async def update_packaging_record(
    record_id: int,
    data: PackagingRecordUpdate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission('production_summary_manage')),
) -> PackagingRecordActionResponse:
    """【已停用，恒返回 410】编辑包装部记录（审计 M-1，2026-11-21）。

    与 create 同一处置：旧表 `packaging_record` 已无页面读取，编辑「成功」等于
    把改动写进黑洞。

    Raises:
        HTTPException: 410 —— 该入口已停用，请改用 `/production` 录入。
    """
    raise HTTPException(
        status_code=410,
        detail=LEGACY_WRITE_GONE_DETAIL,
    )


@router.delete('/packaging/delete/{record_id}', response_model=PackagingRecordActionResponse)
async def delete_packaging_record(
    record_id: int,
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission('production_summary_manage')),
) -> PackagingRecordActionResponse:
    """【已停用，恒返回 410】删除包装部记录（审计 M-1，2026-11-21）。

    与 create 同一处置：旧表 `packaging_record` 已无页面读取，任何页面都看不见
    这条数据的消失，删除只是制造「看起来成功了」的假象。

    Raises:
        HTTPException: 410 —— 该入口已停用，请改用 `/production` 录入。
    """
    raise HTTPException(
        status_code=410,
        detail=LEGACY_WRITE_GONE_DETAIL,
    )


@router.post('/packaging/upload', response_model=PackagingUploadResponse)
async def upload_packaging_excel(
    file: UploadFile = File(..., description='Excel文件'),
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission('production_summary_manage')),
) -> PackagingUploadResponse:
    """【已停用，恒返回 410】批量导入包装部记录（Excel上传）。

    2026-11-16 审计 A-16 收尾（评审 F11）：本端点写的是**旧表** packaging_record，
    与两个 create 端点同源；任何页面都不再读它，继续放行等于让旧客户端/脚本
    「上传成功、但 /production 永远看不到」。与 create 同口径直接 410。
    410 之后的历史校验体（扩展名/体积/魔数/事务）已按审计 L-1（2026-11-21）删除；
    若将来要恢复上传，请从 git 历史找回而不是在本文件里堆死代码。

    Raises:
        HTTPException: 410 —— 该入口已停用，请改用 `/production` 录入。
    """
    raise HTTPException(
        status_code=410,
        detail='该入口已停用，请在 /production 录入生产记录'
               '（本入口写入的是历史旧表，任何页面都不再读取它）',
    )


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
    except ExportLimitError as e:
        # 同手工部导出：行数上界 413（评审 F1）。
        raise HTTPException(status_code=413, detail=str(e)) from e
    except ValueError as e:
        # 日期非法等其余 ValueError 回 400——L-35/N-54（2026-11-21 审计）：类型判别。
        raise HTTPException(status_code=400, detail=str(e)) from e
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
