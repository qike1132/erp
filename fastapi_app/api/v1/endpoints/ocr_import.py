"""
OCR 出货单识别 FastAPI 端点

支持批量上传 PDF / 图片文件，离线 OCR 识别后写入暂存区。
"""
import asyncio
import logging
import os

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.exc import DisconnectionError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.config import settings
from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_any_permission
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.core.validators import magic_signature, matches_upload_magic, require_upload_magic
from fastapi_app.schemas.ocr_import import (
    OcrOrderPreviewItem,
    OcrOrderPreviewResult,
    OcrPdfImportResult,
    OcrPdfPagePreview,
    OcrPdfParsedItem,
    OcrPdfPreviewResult,
)
from fastapi_app.services import ocr_service as svc
from fastapi_app.services.ocr._extractors import OcrDependencyError
from fastapi_app.services.ocr_service import IMAGE_EXTENSIONS
from fastapi_app.shared_models import User

# OCR 文件大小上限，与全局中间件 MAX_REQUEST_BODY_SIZE (10MB) 保持一致
# 避免中间件在 10MB 即拒绝而端点声明 50MB 的配置不一致问题
MAX_OCR_FILE_SIZE = 10 * 1024 * 1024

logger = logging.getLogger(__name__)
router = APIRouter()
SUPPORTED_EXTENSIONS = {'.pdf'} | IMAGE_EXTENSIONS

@router.post('/create-task', summary='创建 OCR 识别任务（获取进度追踪ID）')
async def create_ocr_task(current_user: User=Depends(require_any_permission('batch_import', 'stockout_manage'))):
    """
    创建 OCR 识别任务，返回 task_id。

    前端应先调用此接口获取 task_id，再带 task_id 调用 /upload，
    同时可立即开始轮询 /progress/{task_id} 获取实时进度。
    """
    task_id = await svc.create_progress()
    return {'task_id': task_id}

@router.post('/upload', response_model=OcrPdfImportResult, summary='批量上传出货单识别导入')
async def upload_shipping_docs(files: list[UploadFile]=File(..., description='一个或多个 PDF/图片文件'), session_id: str=Query(..., description='会话ID'), task_id: str=Query('', description='进度追踪ID（由 /create-task 返回）'), db: AsyncSession=Depends(get_async_db), current_user: User=Depends(require_any_permission('batch_import', 'stockout_manage'))):
    """
    批量上传出货单（PDF/图片），通过离线 OCR 识别后导入暂存区。

    - 支持同时上传多个 PDF 或图片文件
    - 支持格式: PDF, PNG, JPG, JPEG, BMP, TIFF, WEBP
    - 使用 RapidOCR 离线识别，不依赖在线 API
    - 识别结果自动写入暂存出货表（staging_stock_out）
    - 返回 task_id 用于查询进度
    """
    # 2026-10-17 审计 P2-23：批量上传必须有数量上限（此前任意多文件全量读入），
    # 且识别写入改为逐文件事务——单文件失败不再回滚整批已成功的结果。
    MAX_OCR_FILES = 50
    if len(files) > MAX_OCR_FILES:
        raise HTTPException(status_code=400, detail=f'单次最多上传 {MAX_OCR_FILES} 个文件')
    # 2026-10-17 审计 AUD-03：进度已迁 Redis，跨 worker 可见。
    # 未传 task_id 时新建；传了但未知（过期/旧客户端）由 _update_progress 自动初始化。
    if not task_id:
        task_id = await svc.create_progress()
    await svc._update_progress(task_id, status='processing', percent=2, message=f'共 {len(files)} 个文件待处理...')
    total_imported = 0
    all_errors: list[str] = []
    file_results: list[dict] = []
    valid_files = 0
    for i, file in enumerate(files):
        filename = file.filename or 'unknown'
        ext = os.path.splitext(filename.lower())[1]
        if ext not in SUPPORTED_EXTENSIONS:
            all_errors.append(f'{filename}: 不支持的文件格式（支持 PDF/图片），已跳过')
            continue
        content = await file.read()
        if len(content) > MAX_OCR_FILE_SIZE:
            all_errors.append(f'{filename}: 文件超过 10MB 限制，已跳过')
            continue
        if len(content) == 0:
            all_errors.append(f'{filename}: 文件为空，已跳过')
            continue
        # P0-12：扩展名通过后再校验文件头（改扩展名的伪 PDF/图片在此拦下，跳过该文件）
        if not matches_upload_magic(content, ext):
            all_errors.append(f'{filename}: 文件内容与扩展名不符（签名 {magic_signature(content)}），已跳过')
            logger.warning('OCR 批量上传魔数校验失败: filename=%s ext=%s %s', filename, ext, magic_signature(content))
            continue
        valid_files += 1
        if len(files) > 1:
            await svc._update_progress(task_id, message=f'正在处理第 {i + 1}/{len(files)} 个文件: {filename}')
        try:
            async with db_transaction(db):
                imported, message, errors = await svc.import_staging_stockouts_from_file(db, content, session_id, filename=filename, task_id=task_id)
        except OcrDependencyError as e:
            # 逐文件如实报出修复指引，别让整批 500（缺依赖时每个文件都会走到这里）
            all_errors.append(f'{filename}: {e!s}')
            logger.error('OCR 批量上传依赖缺失: %s', e)
            continue
        except Exception as e:  # defensive: 单文件失败不得中断整批（其余文件已各自提交）
            all_errors.append(f'{filename}: 处理失败（{e!s}）')
            logger.exception('OCR 批量上传单文件处理失败: %s', filename)
            continue
        total_imported += imported
        if errors:
            all_errors.extend([f'{filename}: {e}' for e in errors])
        file_results.append({'filename': filename, 'imported': imported, 'message': message})
    overall_message = f'共处理 {len(file_results)} 个文件，识别导入 {total_imported} 个出货到暂存区'
    await svc._update_progress(task_id, status='done', percent=100, message=overall_message)
    return OcrPdfImportResult(success=total_imported > 0 or len(file_results) == 0, message=overall_message, total_imported=total_imported, file_count=len(file_results), file_results=file_results, errors=all_errors[:20], task_id=task_id)

@router.get('/progress/{task_id}', summary='查询 OCR 识别进度')
async def get_ocr_progress(task_id: str, current_user: User=Depends(require_any_permission('batch_import', 'stockout_manage'))):
    """
    查询 OCR 识别任务的进度。

    返回当前状态、百分比、消息等信息。
    """
    progress = await svc.get_progress(task_id)
    if progress is None:
        # 明确终态：前端据此停止轮询（此前查不到时静默新建全 0 进度 → 永远 0%）
        return {'status': 'not_found', 'percent': 0, 'message': '任务不存在或已过期'}
    return progress

@router.post('/preview', response_model=OcrPdfPreviewResult, summary='预览 OCR 识别结果（不写入暂存区）')
async def preview_shipping_doc(file: UploadFile=File(..., description='PDF 或图片文件'), current_user: User=Depends(require_any_permission('batch_import', 'stockout_manage'))):
    """
    预览单个文件的 OCR 识别结果，不写入暂存区。

    用于用户确认识别效果后再决定是否正式导入。
    支持 PDF 和图片格式。
    """
    filename = file.filename or 'unknown'
    ext = os.path.splitext(filename.lower())[1]
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail='不支持的文件格式，请上传 PDF 或图片文件')
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail='文件为空')
    if len(content) > MAX_OCR_FILE_SIZE:
        raise HTTPException(status_code=400, detail='文件超过 10MB 限制')
    require_upload_magic(content, ext, filename=filename)  # P0-12：文件头校验，失败 400
    try:
        table_pages = await asyncio.to_thread(svc.extract_table_structure, content, filename)
        if table_pages:
            parsed_items = svc.parse_html_shipping_tables(table_pages)
            if not parsed_items:
                pages = await asyncio.to_thread(svc.extract_text, content, filename)
                if pages:
                    parsed_items = svc.parse_shipping_document(pages)
            else:
                pages = [{'page': p['page'], 'text': p.get('text', '')[:500]} for p in table_pages]
        else:
            pages = await asyncio.to_thread(svc.extract_text, content, filename)
            if pages:
                parsed_items = svc.parse_shipping_document(pages)
            else:
                pages = []
                parsed_items = []
        if not pages and (not parsed_items):
            return OcrPdfPreviewResult(success=False, message='无法提取文本内容', filename=filename, page_count=0, pages=[], parsed_items=[])
        return OcrPdfPreviewResult(success=True, message=f'识别完成，共 {len(pages)} 页，识别到 {len(parsed_items)} 个出货项', filename=filename, page_count=len(pages), pages=[OcrPdfPagePreview(page=p.get('page', 0), text=p.get('text', '')[:500]) for p in pages], parsed_items=[OcrPdfParsedItem.model_validate(it) for it in parsed_items])
    except OcrDependencyError as e:
        # 缺 OCR 可选依赖是可预期的部署状态：明确告知修复方式。
        # 不这样兜的话，用户只看到「服务器内部错误」，真因只躺在日志里（2026-10-08 生产事故）。
        logger.error('OCR 依赖缺失（预览）: %s', e)
        raise HTTPException(status_code=503, detail=str(e)) from e
    except (OperationalError, DisconnectionError) as e:
        logger.error(f'OCR 预览失败: {e!s}', exc_info=True)
        raise HTTPException(status_code=500, detail=f'识别失败: {settings.sanitize_error(e)}') from e


@router.post('/order/preview', response_model=OcrOrderPreviewResult, summary='订单图片识别预览（不写暂存区）')
async def preview_order_doc(
    file: UploadFile = File(..., description='订单图片或 PDF（支持粘贴上传的截图）'),
    customer: str = Query('', description='表单当前选中的客户名，图上没有客户信息时兜底'),
    db: AsyncSession = Depends(get_async_read_db),
    # 「客户订单」页与「出货」页共用这条识别预览链路（前端 components/ocr），
    # 两边的页面权限码都放行：任何能进对应录入页的用户都能预览（本端点不写库）。
    current_user: User = Depends(require_any_permission('batch_import', 'order_manage', 'stockout_manage')),
):
    """识别订单图片（聊天截图 / 表格 / 拍照），返回待人工确认的条目。

    **不写库**：结果由前端在预览弹窗里人工核对、修正后，再作为暂存条目进入批量提交流程。
    因此这里不做任何写入，也不改暂存区。
    """
    filename = file.filename or 'unknown'
    ext = os.path.splitext(filename.lower())[1]
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail='不支持的文件格式，请上传图片或 PDF')
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail='文件为空')
    if len(content) > MAX_OCR_FILE_SIZE:
        raise HTTPException(status_code=400, detail='文件超过 10MB 限制')
    require_upload_magic(content, ext, filename=filename)  # P0-12：文件头校验，失败 400
    try:
        items, raw_text, warnings = await svc.preview_order_items(db, content, filename, customer)
    except OcrDependencyError as e:
        # 客户端按 503 展示可读指引；前端「粘贴识别」的失败提示会带上这句话
        logger.error('OCR 依赖缺失（订单预览）: %s', e)
        raise HTTPException(status_code=503, detail=str(e)) from e
    except (OperationalError, DisconnectionError) as e:
        logger.error(f'OCR 订单识别失败: {e!s}', exc_info=True)
        raise HTTPException(status_code=500, detail=f'识别失败: {settings.sanitize_error(e)}') from e
    if not items:
        return OcrOrderPreviewResult(
            success=False,
            message='没有识别到可导入的条目',
            filename=filename,
            item_count=0,
            items=[],
            raw_text=raw_text,
            warnings=warnings,
        )
    return OcrOrderPreviewResult(
        success=True,
        message=f'识别到 {len(items)} 项，请核对后导入',
        filename=filename,
        item_count=len(items),
        items=[OcrOrderPreviewItem.model_validate(it) for it in items],
        raw_text=raw_text,
        warnings=warnings,
    )
