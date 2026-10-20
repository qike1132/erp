"""
异步任务 API 端点
任务提交与状态查询，基于 ARQ（原生 async 任务队列）。
"""
import contextlib
import os
import shutil
import tempfile
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from fastapi_app.core.deps import require_any_permission, require_permission
from fastapi_app.core.logger import logger
from fastapi_app.core.response import success_response
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
        # 第十轮审计：原仅查首字节 —— 改名 .csv 的二进制（zip/PK 等）首字节可能可打印
        # 而蒙混过关。检查整个 8 字节头：出现非文本控制字符（Tab/LF/CR 除外）即拒绝。
        if any(b < 0x20 and b not in (0x09, 0x0a, 0x0d) for b in header):
            raise HTTPException(status_code=400, detail="CSV 文件包含非法控制字符，可能不是文本文件")

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


# 异步导出支持的报表类型 —— 必须与 /reports/export 的 ALLOWED_REPORT_TYPES、
# report_data_service.get_all_logs_data / ReportExporter 的分支保持同口径
# （tests/test_report.py::TestExportTypeParity 钉住三处一致）。
ASYNC_EXPORT_REPORT_TYPES = ('order', 'stockin', 'stockout', 'deduction', 'return')


class ReportExportRequest(BaseModel):
    report_type: str  # 见 ASYNC_EXPORT_REPORT_TYPES
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
    # 本端点同时服务导入任务(batch_import)与报表导出(report_view)，
    # 任一权限即可轮询；否则报表导出提交(需 report_view)后无法查状态
    current_user: User = Depends(require_any_permission("batch_import", "report_view")),
):
    """查询 ARQ 异步任务状态"""
    job = await _get_arq_job(task_id)
    status, result = await _job_status(job)

    if status == "NOT_FOUND":
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在或已过期")

    # Z06-R4：导出任务带归属前缀，非本人一律 404（与 download 端点同口径）；
    # 其余历史任务保持可查，但响应中剔除服务器内部路径（file_path 仅下载端点内部使用）。
    if task_id.startswith('exp-u') and not task_id.startswith(f'exp-u{current_user.id}-'):
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在或已过期")

    response = TaskStatusResponse(task_id=task_id, status=status)
    if result is not None:
        payload = result if isinstance(result, dict) else {"value": result}
        if isinstance(payload, dict):
            payload = {k: v for k, v in payload.items() if k not in ('file_path', 'filepath', 'path')}
        response.result = payload
    return response


# ==================== 批量导入（异步） ====================

@router.post("/import-orders", response_model=AsyncTaskSubmitResponse)
async def async_import_orders(
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission("batch_import")),
):
    """异步批量导入订单（提交后台任务）

    已知缺口：本端点**不走** ``import_guard.run_guarded_import``（文件指纹幂等）。
    导入在 ARQ worker 中异步执行、与请求级事务分离，无法原子登记文件哈希；
    故同一文件重复上传会重复建单，去重仅到 ARQ job_id 级（防 ``max_tries`` 重投）。
    详见 ``api/v1/endpoints/import_guard.py`` 模块文档。
    """
    _validate_import_file(file)

    suffix = os.path.splitext(file.filename or '')[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    from fastapi_app.core.arq_app import get_arq_pool
    from fastapi_app.tasks.batch_tasks import batch_import_orders_task
    try:
        pool = await get_arq_pool()
        job = await pool.enqueue_job(batch_import_orders_task.__name__, tmp_path, file.filename, current_user.id)
    except Exception:  # defensive: 入队失败须清理临时文件，异常类型取决于 Redis 驱动
        # 第八轮审计：入队失败（如 Redis 不可用）时清理临时文件，避免 %TEMP% 堆积
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise
    task_id_str = job.job_id if job else ''

    return success_response(**{
        "message": "批量导入任务已提交",
        "task_id": task_id_str,
        "status_url": f"/api/v1/tasks/status/{task_id_str}"})


@router.post("/import-stockins", response_model=AsyncTaskSubmitResponse)
async def async_import_stockins(
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission("batch_import")),
):
    """异步批量导入备货（提交后台任务）

    已知缺口：同 ``/tasks/import-orders`` —— 本端点**不走**文件指纹幂等守卫，
    重复上传同一文件会重复入库；详见 ``api/v1/endpoints/import_guard.py`` 模块文档。
    """
    _validate_import_file(file)

    suffix = os.path.splitext(file.filename or '')[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    from fastapi_app.core.arq_app import get_arq_pool
    from fastapi_app.tasks.batch_tasks import batch_import_stockins_task
    try:
        pool = await get_arq_pool()
        job = await pool.enqueue_job(batch_import_stockins_task.__name__, tmp_path, file.filename, current_user.id)
    except Exception:  # defensive: 入队失败须清理临时文件，异常类型取决于 Redis 驱动
        # 第八轮审计：入队失败（如 Redis 不可用）时清理临时文件，避免 %TEMP% 堆积
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise
    task_id_str = job.job_id if job else ''

    return success_response(**{
        "message": "批量导入任务已提交",
        "task_id": task_id_str,
        "status_url": f"/api/v1/tasks/status/{task_id_str}"})


# ==================== 报表导出（异步） ====================

@router.post("/export-report", response_model=AsyncTaskSubmitResponse)
async def async_export_report(
    request: ReportExportRequest,
    # Round16：报表导出改 report_view（与同步导出端点一致），原 batch_import 与
    # 报表无关——任何持导入权限者可读全量报表属权限面放大
    current_user: User = Depends(require_permission("report_view")),
):
    """异步导出报表（提交后台任务）"""
    if request.report_type not in ASYNC_EXPORT_REPORT_TYPES:
        raise HTTPException(status_code=400, detail=f"不支持的报表类型: {request.report_type}")

    # 工厂隔离与同步导出（report.py）同口径：非超管且绑定工厂只导本厂。
    # Round16：原 filters 漏 factory，厂绑定用户可经异步任务导出他厂全部流水。
    from fastapi_app.api.v1.endpoints.report import _factory_scope
    from fastapi_app.core.arq_app import get_arq_pool
    from fastapi_app.tasks.report_tasks import export_report_task
    filters = {
        "customer": request.customer,
        "product": request.product,
        "status": request.status,
        "start_date": request.start_date,
        "end_date": request.end_date,
        "factory": _factory_scope(current_user),
    }

    pool = await get_arq_pool()
    # 第十轮审计：导出任务 job_id 带归属前缀，download 端点据此校验归属
    #（原任何持 batch_import 者凭 task_id 可下载他人导出文件）。
    job = await pool.enqueue_job(
        export_report_task.__name__, request.report_type, filters, current_user.id,
        _job_id=f'exp-u{current_user.id}-{uuid4().hex}',
    )
    task_id = job.job_id if job else ''

    return success_response(**{
        "message": "报表导出任务已提交",
        "task_id": task_id,
        "status_url": f"/api/v1/tasks/status/{task_id}"})


# ==================== 导出文件下载 ====================

@router.get("/download/{task_id}")
async def download_task_result(
    task_id: str,
    # 同 status：导入任务与报表导出共用，任一权限即可下载
    current_user: User = Depends(require_any_permission("batch_import", "report_view")),
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

    # 归属校验：导出任务的 job_id 带 `exp-u{uid}-` 前缀，非本人任务一律 404
    #（既不泄露他人任务存在性，也不泄露其导出文件）。
    if task_id.startswith('exp-u'):
        expected = f'exp-u{current_user.id}-'
        if not task_id.startswith(expected):
            raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在或已过期")

    file_path = result.get("file_path")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="导出文件不存在或已过期")

    from fastapi.responses import FileResponse
    from starlette.background import BackgroundTask
    filename = result.get("filename", "export.xlsx")

    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        background=BackgroundTask(_cleanup_file, file_path),
    )


def _cleanup_file(file_path: str):
    """响应完成后清理临时文件"""
    try:
        if os.path.exists(file_path):
            os.unlink(file_path)
    except OSError:
        pass  # defensive: 异常静默处理,不影响主流程
