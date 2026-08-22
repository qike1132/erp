"""
异步任务 API 端点
任务提交与状态查询，基于 ARQ（原生 async 任务队列）。
"""
import os
import shutil
import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from fastapi_app.core.deps import require_permission
from fastapi_app.core.logger import logger
from fastapi_app.shared_models import User

# ARQ Job 状态 → 对外状态映射
# JobStatus: deferred / queued / in_progress / complete / not_found
_JOB_STATUS_MAP = {
    "deferred": "PENDING",
    "queued": "PENDING",
    "in_progress": "STARTED",
    "complete": "SUCCESS",
    "not_found": "NOT_FOUND",
}

router = APIRouter(tags=["异步任务"])

MAX_IMPORT_FILE_SIZE = 50 * 1024 * 1024  # 50MB

VALID_FILE_SIGNATURES = {
    '.xlsx': (b'PK\x03\x04', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
    '.csv': None,  # CSV 无固定魔数，纯文本检测
}

async def _get_arq_job(task_id: str):
    """获取 ARQ Job 对象（Redis 不可用时抛出 503）"""
    try:
        from arq.jobs import Job

        from fastapi_app.core.arq_app import get_arq_pool
        pool = await get_arq_pool()
        return Job(task_id, pool)
    except Exception as e:  # broad-except: Redis/连接异常统一降级 503
        logger.warning("ARQ 连接不可用，异步任务功能暂不可用: %s", e)
        raise HTTPException(status_code=503, detail="异步任务服务暂不可用，请稍后重试") from e

async def _job_status(job) -> tuple[str, dict | None]:
    """查询 ARQ Job 状态，返回 (状态, 结果)"""
    from arq.jobs import JobStatus
    try:
        status = await job.status()
    except Exception as e:  # broad-except: Redis 查询失败统一降级
        logger.warning("ARQ Job 状态查询失败: %s", e)
        raise HTTPException(status_code=503, detail="异步任务服务暂不可用，请稍后重试") from e

    if status == JobStatus.not_found:
        return "NOT_FOUND", None

    external_status = _JOB_STATUS_MAP.get(str(status.value), str(status.value).upper())

    if status == JobStatus.complete:
        info = await job.result_info()
        if info is not None:
            if info.success:
                return external_status, info.result
            return "FAILURE", {"error": repr(info.result) if isinstance(info.result, Exception) else info.result}

    return external_status, None

def _validate_import_file(file: UploadFile) -> None:
    filename = file.filename or ''
    ext = os.path.splitext(filename)[1].lower()
    if ext not in VALID_FILE_SIGNATURES:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}，仅支持 .xlsx / .csv")

    header = file.file.read(8)
    file_size = len(header)
    if file_size < 4 and ext == '.xlsx':
        raise HTTPException(status_code=400, detail="文件内容为空或过小")

    sig_info = VALID_FILE_SIGNATURES[ext]
    if sig_info is not None:
        expected_sig, _ = sig_info
        if header[:len(expected_sig)] != expected_sig:
            raise HTTPException(status_code=400, detail=f"文件内容与扩展名不匹配，可能不是有效的 {ext} 文件")
    elif ext == '.csv':
        if header and header[0] < 0x20 and header[0] not in (0x09, 0x0a, 0x0d):
            raise HTTPException(status_code=400, detail="CSV 文件包含非法控制字符")

    file.file.seek(0)

    file.file.seek(0, 2)
    total_size = file.file.tell()
    file.file.seek(0)
    if total_size > MAX_IMPORT_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"文件大小超过 {MAX_IMPORT_FILE_SIZE // 1024 // 1024}MB 限制")


# ==================== Schemas ====================

class TaskStatusResponse(BaseModel):
    task_id: str
    status: str  # PENDING, STARTED, SUCCESS, FAILURE, NOT_FOUND
    result: dict | None = None
    progress: float | None = None


class ReportExportRequest(BaseModel):
    report_type: str  # order, stockin, stockout, deduction
    customer: str = ""
    product: str = ""
    status: str = ""
    start_date: str = ""
    end_date: str = ""


class AsyncTaskSubmitResponse(BaseModel):
    success: bool
    message: str
    task_id: str
    status_url: str


# ==================== 任务状态查询 ====================

@router.get("/status/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: str,
    current_user: User = Depends(require_permission("batch_import")),
):
    """查询 ARQ 异步任务状态"""
    job = await _get_arq_job(task_id)
    status, result = await _job_status(job)

    if status == "NOT_FOUND":
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在或已过期")

    response = TaskStatusResponse(task_id=task_id, status=status)
    if result is not None:
        response.result = result if isinstance(result, dict) else {"value": result}
    return response


# ==================== 批量导入（异步） ====================

@router.post("/import-orders", response_model=AsyncTaskSubmitResponse)
async def async_import_orders(
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission("batch_import")),
):
    """异步批量导入订单（提交后台任务）"""
    _validate_import_file(file)

    suffix = os.path.splitext(file.filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    from fastapi_app.core.arq_app import get_arq_pool
    from fastapi_app.tasks.batch_tasks import batch_import_orders_task
    pool = await get_arq_pool()
    job = await pool.enqueue_job(batch_import_orders_task.__name__, tmp_path, file.filename, current_user.id)
    task_id_str = job.job_id if job else ''

    return {
        "success": True,
        "message": "批量导入任务已提交",
        "task_id": task_id_str,
        "status_url": f"/api/v1/tasks/status/{task_id_str}",
    }


@router.post("/import-stockins", response_model=AsyncTaskSubmitResponse)
async def async_import_stockins(
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission("batch_import")),
):
    """异步批量导入备货（提交后台任务）"""
    _validate_import_file(file)

    suffix = os.path.splitext(file.filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    from fastapi_app.core.arq_app import get_arq_pool
    from fastapi_app.tasks.batch_tasks import batch_import_stockins_task
    pool = await get_arq_pool()
    job = await pool.enqueue_job(batch_import_stockins_task.__name__, tmp_path, file.filename, current_user.id)
    task_id_str = job.job_id if job else ''

    return {
        "success": True,
        "message": "批量导入任务已提交",
        "task_id": task_id_str,
        "status_url": f"/api/v1/tasks/status/{task_id_str}",
    }


# ==================== 报表导出（异步） ====================

@router.post("/export-report", response_model=AsyncTaskSubmitResponse)
async def async_export_report(
    request: ReportExportRequest,
    current_user: User = Depends(require_permission("batch_import")),
):
    """异步导出报表（提交后台任务）"""
    if request.report_type not in ("order", "stockin", "stockout", "deduction"):
        raise HTTPException(status_code=400, detail=f"不支持的报表类型: {request.report_type}")

    from fastapi_app.core.arq_app import get_arq_pool
    from fastapi_app.tasks.report_tasks import export_report_task

    filters = {
        "customer": request.customer,
        "product": request.product,
        "status": request.status,
        "start_date": request.start_date,
        "end_date": request.end_date,
    }

    pool = await get_arq_pool()
    job = await pool.enqueue_job(export_report_task.__name__, request.report_type, filters, current_user.id)
    task_id = job.job_id if job else ''

    return {
        "success": True,
        "message": "报表导出任务已提交",
        "task_id": task_id,
        "status_url": f"/api/v1/tasks/status/{task_id}",
    }


# ==================== 导出文件下载 ====================

@router.get("/download/{task_id}")
async def download_task_result(
    task_id: str,
    current_user: User = Depends(require_permission("batch_import")),
):
    """下载 ARQ 异步任务生成的文件"""
    job = await _get_arq_job(task_id)
    status, result = await _job_status(job)

    if status == "NOT_FOUND":
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在或已过期")
    if status != "SUCCESS":
        raise HTTPException(status_code=202, detail="任务尚未完成")

    if not isinstance(result, dict):
        raise HTTPException(status_code=500, detail="任务结果格式异常")

    file_path = result.get("file_path")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="导出文件不存在或已过期")

    from fastapi.responses import FileResponse
    filename = result.get("filename", "export.xlsx")

    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        background=lambda: _cleanup_file(file_path),
    )


def _cleanup_file(file_path: str):
    """响应完成后清理临时文件"""
    try:
        if os.path.exists(file_path):
            os.unlink(file_path)
    except OSError:
        pass  # defensive: 异常静默处理,不影响主流程
