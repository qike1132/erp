"""
批量导入 FastAPI 端点

职责：
- 提供统一导入模板下载接口
- 提供订单、备货、出库、皮套出库/入库、产品的批量导入接口
- 提供综合批量导入接口（支持4个Sheet自动识别）
"""
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.api.v1.endpoints.import_guard import (
    TYPE_CASE_STOCKINS,
    TYPE_CASE_STOCKOUTS,
    TYPE_COMPREHENSIVE,
    TYPE_ORDERS,
    TYPE_PRODUCTS,
    TYPE_STOCKINS,
    TYPE_STOCKOUTS,
    run_guarded_import,
)
from fastapi_app.core.database import get_async_db
from fastapi_app.core.deps import require_any_permission, require_permission
from fastapi_app.schemas.batch import (
    BatchImportResult,
    ComprehensiveImportResult,
    ProductImportPreviewResult,
)
from fastapi_app.services.batch_import_service import (
    import_case_stockins_service,
    import_case_stockouts_service,
    import_comprehensive_service,
    import_orders_service,
    import_products_service,
    import_stockins_service,
    import_stockouts_service,
    preview_products_service,
    read_template_bytes,
)
from fastapi_app.shared_models import User

router = APIRouter()


@router.get('/download-template', summary='下载统一导入模板')
async def download_template(
    # 统一导入模板被「客户订单」「出库管理」「出货计划」三个页面共用（各自页面工具栏）。
    current_user: User = Depends(require_any_permission(
        'batch_import', 'order_manage', 'stockout_manage', 'production_plan_view')),
) -> Response:
    """下载统一导入模板 - 直接读取静态文件。

    Args:
        current_user: 当前登录用户（仅需通过权限校验）。

    Returns:
        Response: Excel 文件流响应。

    Raises:
        HTTPException: 模板文件不存在时抛出 404；读取失败时抛出 500。
    """
    file_content, filename = await read_template_bytes()
    return Response(
        content=file_content,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={
            'Content-Disposition': f"attachment; filename*=UTF-8''{quote(filename)}",
            'Content-Length': str(len(file_content)),
            'Cache-Control': 'no-cache, no-store, must-revalidate',
        },
    )


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
    return await run_guarded_import(
        db, file, TYPE_ORDERS, current_user,
        lambda f: import_orders_service(db, f),
    )


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
    return await run_guarded_import(
        db, file, TYPE_CASE_STOCKOUTS, current_user,
        lambda f: import_case_stockouts_service(db, f),
    )


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
    return await run_guarded_import(
        db, file, TYPE_CASE_STOCKINS, current_user,
        lambda f: import_case_stockins_service(db, f),
    )


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
    # 工厂闸门（审查 H1，P0-2 补漏）：厂绑定用户经 Excel 导入写他厂产品
    # 的库存此前零校验（单行/aux 批量端点均已闸，导入链漏网）。scoped 为
    # 空表示超管/未绑定厂，服务层全部放行。
    scoped_factory = current_user.factory if (current_user.factory and not current_user.is_super) else None
    return await run_guarded_import(
        db, file, TYPE_STOCKINS, current_user,
        lambda f: import_stockins_service(db, f, scoped_factory=scoped_factory),
    )


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
    # 工厂闸门（审查 H1）：与 /import-stockins 同口径
    scoped_factory = current_user.factory if (current_user.factory and not current_user.is_super) else None
    return await run_guarded_import(
        db, file, TYPE_STOCKOUTS, current_user,
        lambda f: import_stockouts_service(db, f, scoped_factory=scoped_factory),
    )


@router.post('/batch-import/preview', response_model=ProductImportPreviewResult,
             summary='预览产品批量导入（不写库）')
async def preview_batch_import_products(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_permission('batch_import')),
) -> ProductImportPreviewResult:
    """预览产品批量导入 —— 逐行分类，**不写库、不落图片**。

    用户先在这里核对「将新增/补全/跳过哪些行、客户与价格识别成了什么」，确认后前端
    把同一文件重发给 ``POST /batch/batch-import`` 才真正入库。

    两处刻意的选择：
    - **不经 ``run_guarded_import``**：那个守卫会登记文件指纹（同文件只允许导入一次）。
      预览必须可重复，且不能把用户的文件提前锁死。
    - **用主库会话**（非只读副本）：预览要与随后在主库上的导入同口径，副本延迟会让
      「预览说新增、导入说已存在」这类错位出现。

    Args:
        file: 上传的 Excel 文件（.xlsx 格式）。
        db: 异步数据库会话（本端点只读使用）。
        current_user: 当前登录用户（仅需通过权限校验）。

    Returns:
        ProductImportPreviewResult: 逐行结果与汇总计数。
    """
    return await preview_products_service(db, file)


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
    return await run_guarded_import(
        db, file, TYPE_PRODUCTS, current_user,
        lambda f: import_products_service(db, f, uploader_id=current_user.id),
    )


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
    # 工厂闸门（审查 H1）：仅透传给备货/出货 Sheet（订单/产品 Sheet 语义待业务确认）
    scoped_factory = current_user.factory if (current_user.factory and not current_user.is_super) else None
    return await run_guarded_import(
        db, file, TYPE_COMPREHENSIVE, current_user,
        lambda f: import_comprehensive_service(
            db, f, uploader_id=current_user.id, scoped_factory=scoped_factory,
        ),
    )
