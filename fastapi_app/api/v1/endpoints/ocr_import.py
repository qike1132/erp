"""
OCR 出货单识别 FastAPI 端点

支持批量上传 PDF / 图片文件，离线 OCR 识别后写入暂存区。
"""
import logging
import os

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.exc import DisconnectionError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db
from fastapi_app.core.deps import require_permission
from fastapi_app.schemas.ocr_import import OcrPdfImportResult, OcrPdfPreviewResult
from fastapi_app.services import ocr_service as svc
from fastapi_app.services.ocr_service import IMAGE_EXTENSIONS
from fastapi_app.shared_models import User

logger = logging.getLogger(__name__)
router = APIRouter()
SUPPORTED_EXTENSIONS = {'.pdf'} | IMAGE_EXTENSIONS

@router.post('/create-task', summary='创建 OCR 识别任务（获取进度追踪ID）')
async def create_ocr_task(current_user: User=Depends(require_permission('batch_import'))):
    """
    创建 OCR 识别任务，返回 task_id。

    前端应先调用此接口获取 task_id，再带 task_id 调用 /upload，
    同时可立即开始轮询 /progress/{task_id} 获取实时进度。
    """
    task_id = svc.create_progress()
    return {'task_id': task_id}

@router.post('/upload', response_model=OcrPdfImportResult, summary='批量上传出货单识别导入')
async def upload_shipping_docs(files: list[UploadFile]=File(..., description='一个或多个 PDF/图片文件'), session_id: str=Query(..., description='会话ID'), task_id: str=Query('', description='进度追踪ID（由 /create-task 返回）'), db: AsyncSession=Depends(get_async_db), current_user: User=Depends(require_permission('batch_import'))):
    """
    批量上传出货单（PDF/图片），通过离线 OCR 识别后导入暂存区。

    - 支持同时上传多个 PDF 或图片文件
    - 支持格式: PDF, PNG, JPG, JPEG, BMP, TIFF, WEBP
    - 使用 RapidOCR 离线识别，不依赖在线 API
    - 识别结果自动写入暂存出货表（staging_stock_out）
    - 返回 task_id 用于查询进度
    """
    if not task_id or task_id not in svc._progress_store:
        task_id = svc.create_progress()
    svc._update_progress(task_id, status='processing', percent=2, message=f'共 {len(files)} 个文件待处理...')
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
        if len(content) > 50 * 1024 * 1024:
            all_errors.append(f'{filename}: 文件超过 50MB 限制，已跳过')
            continue
        if len(content) == 0:
            all_errors.append(f'{filename}: 文件为空，已跳过')
            continue
        valid_files += 1
        if len(files) > 1:
            svc._update_progress(task_id, message=f'正在处理第 {i + 1}/{len(files)} 个文件: {filename}')
        imported, message, errors = await svc.import_staging_stockouts_from_file(db, content, session_id, filename=filename, task_id=task_id)
        total_imported += imported
        if errors:
            all_errors.extend([f'{filename}: {e}' for e in errors])
        file_results.append({'filename': filename, 'imported': imported, 'message': message})
    overall_message = f'共处理 {len(file_results)} 个文件，识别导入 {total_imported} 个出货到暂存区'
    svc._update_progress(task_id, status='done', percent=100, message=overall_message)
    return OcrPdfImportResult(success=total_imported > 0 or len(file_results) == 0, message=overall_message, total_imported=total_imported, file_count=len(file_results), file_results=file_results, errors=all_errors[:20], task_id=task_id)

@router.get('/progress/{task_id}', summary='查询 OCR 识别进度')
async def get_ocr_progress(task_id: str, current_user: User=Depends(require_permission('batch_import'))):
    """
    查询 OCR 识别任务的进度。

    返回当前状态、百分比、消息等信息。
    """
    progress = svc.get_progress(task_id)
    return progress

@router.post('/preview', response_model=OcrPdfPreviewResult, summary='预览 OCR 识别结果（不写入暂存区）')
async def preview_shipping_doc(file: UploadFile=File(..., description='PDF 或图片文件'), current_user: User=Depends(require_permission('batch_import'))):
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
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail='文件超过 50MB 限制')
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        table_pages = await loop.run_in_executor(None, svc.extract_table_structure, content, filename)
        if table_pages:
            parsed_items = svc.parse_html_shipping_tables(table_pages)
            if not parsed_items:
                pages = await loop.run_in_executor(None, svc.extract_text, content, filename)
                if pages:
                    parsed_items = svc.parse_shipping_document(pages)
            else:
                pages = [{'page': p['page'], 'text': p.get('text', '')[:500]} for p in table_pages]
        else:
            pages = await loop.run_in_executor(None, svc.extract_text, content, filename)
            if pages:
                parsed_items = svc.parse_shipping_document(pages)
            else:
                pages = []
                parsed_items = []
        if not pages and (not parsed_items):
            return OcrPdfPreviewResult(success=False, message='无法提取文本内容', filename=filename, page_count=0, pages=[], parsed_items=[])
        return OcrPdfPreviewResult(success=True, message=f'识别完成，共 {len(pages)} 页，识别到 {len(parsed_items)} 个出货项', filename=filename, page_count=len(pages), pages=[{'page': p.get('page', 0), 'text': p.get('text', '')[:500]} for p in pages], parsed_items=parsed_items)
    except (OperationalError, DisconnectionError) as e:
        logger.error(f'OCR 预览失败: {str(e)}', exc_info=True)
        raise HTTPException(status_code=500, detail=f'识别失败: {str(e)}') from e
