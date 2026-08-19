"""
批量导入 FastAPI 端点

职责：
- 提供统一导入模板下载接口
- 提供订单、备货、出库、皮套出库/入库、产品的批量导入接口
- 提供综合批量导入接口（支持4个Sheet自动识别）
"""
from fastapi import APIRouter, Depends, File, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db
from fastapi_app.core.deps import require_permission
from fastapi_app.schemas.batch import BatchImportResult, ComprehensiveImportResult
from fastapi_app.services.batch_import_service import (
    download_template_service,
    import_case_stockins_service,
    import_case_stockouts_service,
    import_comprehensive_service,
    import_orders_service,
    import_products_service,
    import_stockins_service,
    import_stockouts_service,
)
from fastapi_app.shared_models import User

router = APIRouter()


@router.get('/download-template', summary='下载统一导入模板')
async def download_template(
    current_user: User = Depends(require_permission('batch_import')),
) -> Response:
    """下载统一导入模板 - 直接读取静态文件。

    Args:
        current_user: 当前登录用户（仅需通过权限校验）。

    Returns:
        Response: Excel 文件流响应。

    Raises:
        HTTPException: 模板文件不存在时抛出 404；读取失败时抛出 500。
    """
    return await download_template_service()


@router.post('/import-orders', response_model=BatchImportResult, summary='批量导入订单')
async def batch_import_orders(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_permission('batch_import')),
) -> BatchImportResult:
    """批量导入订单 - 支持统一模板格式。

    Args:
        file: 上传的 Excel 文件（.xlsx 格式）。
        db: 异步数据库会话（读写主库）。
        current_user: 当前登录用户（仅需通过权限校验）。

    Returns:
        BatchImportResult: 包含导入结果、消息和条数的响应。
    """
    return await import_orders_service(db, file)


@router.post('/import-case-stockouts', response_model=BatchImportResult, summary='批量导入皮套出库')
async def batch_import_case_stockouts(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_permission('case_manage')),
) -> BatchImportResult:
    """批量导入皮套出库。

    Args:
        file: 上传的 Excel 文件（.xlsx 格式）。
        db: 异步数据库会话（读写主库）。
        current_user: 当前登录用户（仅需通过权限校验）。

    Returns:
        BatchImportResult: 包含导入结果、消息和条数的响应。
    """
    return await import_case_stockouts_service(db, file)


@router.post('/import-case-stockins', response_model=BatchImportResult, summary='批量导入皮套入库')
async def batch_import_case_stockins(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_permission('case_manage')),
) -> BatchImportResult:
    """批量导入皮套入库。

    Args:
        file: 上传的 Excel 文件（.xlsx 格式）。
        db: 异步数据库会话（读写主库）。
        current_user: 当前登录用户（仅需通过权限校验）。

    Returns:
        BatchImportResult: 包含导入结果、消息和条数的响应。
    """
    return await import_case_stockins_service(db, file)


@router.post('/import-stockins', response_model=BatchImportResult, summary='批量导入备货')
async def batch_import_stockins(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_permission('batch_import')),
) -> BatchImportResult:
    """批量导入备货 - 支持统一导入模板。

    Args:
        file: 上传的 Excel 文件（.xlsx 格式）。
        db: 异步数据库会话（读写主库）。
        current_user: 当前登录用户（仅需通过权限校验）。

    Returns:
        BatchImportResult: 包含导入结果、消息和条数的响应。
    """
    return await import_stockins_service(db, file)


@router.post('/import-stockouts', response_model=BatchImportResult, summary='批量导入出库')
async def batch_import_stockouts(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_permission('batch_import')),
) -> BatchImportResult:
    """批量导入出库。

    Args:
        file: 上传的 Excel 文件（.xlsx 格式）。
        db: 异步数据库会话（读写主库）。
        current_user: 当前登录用户（仅需通过权限校验）。

    Returns:
        BatchImportResult: 包含导入结果、消息和条数的响应。
    """
    return await import_stockouts_service(db, file)


@router.post('/batch-import', response_model=BatchImportResult, summary='批量导入产品')
async def batch_import_products(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_permission('batch_import')),
) -> BatchImportResult:
    """批量导入产品 - 支持统一模板格式。

    Args:
        file: 上传的 Excel 文件（.xlsx 格式）。
        db: 异步数据库会话（读写主库）。
        current_user: 当前登录用户（仅需通过权限校验）。

    Returns:
        BatchImportResult: 包含导入结果、消息和条数的响应。
    """
    return await import_products_service(db, file)


@router.post('/import-comprehensive', response_model=ComprehensiveImportResult, summary='综合批量导入')
async def batch_import_comprehensive(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_permission('batch_import')),
) -> ComprehensiveImportResult:
    """综合批量导入 - 支持4个Sheet自动识别。

    自动识别 Sheet 类型：产品管理、订单管理、备货管理、出货管理。
    每个 Sheet 独立处理，单个 Sheet 失败不影响其他 Sheet。

    Args:
        file: 上传的 Excel 文件（.xlsx 格式）。
        db: 异步数据库会话（读写主库）。
        current_user: 当前登录用户（仅需通过权限校验）。

    Returns:
        ComprehensiveImportResult: 包含各类型导入数量和错误列表的响应。
    """
    return await import_comprehensive_service(db, file)
