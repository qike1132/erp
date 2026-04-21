"""
异步任务 API 端点
提供 Celery 任务的提交和状态查询
若 Celery 未安装，端点返回 503 提示
"""
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from pydantic import BaseModel
from typing import Optional
import tempfile
import os
import shutil
import logging

from fastapi_app.core.logger import logger
from fastapi_app.core.deps import require_permission
from fastapi_app.shared_models import User

# Celery 懒加载：避免顶层导入导致缺失 celery 包时整个应用无法启动
_celery_app = None
_celery_available = None

def _get_celery_app():
    global _celery_app, _celery_available
    if _celery_available is None:
        try:
            from fastapi_app.core.celery_app import celery_app
            _celery_app = celery_app
            _celery_available = True
        except ImportError:
            _celery_available = False
            logger.warning("Celery 未安装或配置不可用，异步任务功能已禁用")
    return _celery_app

def _require_celery():
    """检查 Celery 是否可用，不可用时抛出 503"""
    app = _get_celery_app()
    if app is None:
        raise HTTPException(status_code=503, detail="Celery 服务未配置，异步任务功能不可用")
    return app

router = APIRouter(prefix="/tasks", tags=["异步任务"])


# ==================== Schemas ====================

class TaskStatusResponse(BaseModel):
    task_id: str
    status: str  # PENDING, STARTED, SUCCESS, FAILURE, RETRY, REVOKED
    result: Optional[dict] = None
    progress: Optional[float] = None


class ReportExportRequest(BaseModel):
    report_type: str  # order, stockin, stockout, deduction
    customer: str = ""
    product: str = ""
    status: str = ""
    start_date: str = ""
    end_date: str = ""


# ==================== 任务状态查询 ====================

@router.get("/status/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: str,
    current_user: User = Depends(require_permission("batch_import")),
):
    """查询异步任务状态"""
    celery_app = _require_celery()
    result = celery_app.AsyncResult(task_id)

    response = TaskStatusResponse(
        task_id=task_id,
        status=result.status,
    )

    if result.ready():
        if result.successful():
            response.result = result.result
        else:
            response.result = {"error": str(result.result)}

    return response


# ==================== 批量导入（异步） ====================

@router.post("/import-orders")
async def async_import_orders(
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission("batch_import")),
):
    """异步批量导入订单（提交后台任务）"""
    if not file.filename.endswith(('.xlsx', '.csv')):
        raise HTTPException(status_code=400, detail="仅支持 Excel (.xlsx) 或 CSV 文件，.xls 已不再支持")

    # 保存上传文件到临时位置
    suffix = os.path.splitext(file.filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    # 提交 Celery 任务
    from fastapi_app.tasks.batch_tasks import batch_import_orders_task
    task = batch_import_orders_task.delay(tmp_path, file.filename, user_id=current_user.id)

    return {
        "success": True,
        "message": "批量导入任务已提交",
        "task_id": task.id,
        "status_url": f"/api/v1/tasks/status/{task.id}",
    }


@router.post("/import-stockins")
async def async_import_stockins(
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission("batch_import")),
):
    """异步批量导入备货（提交后台任务）"""
    if not file.filename.endswith(('.xlsx', '.csv')):
        raise HTTPException(status_code=400, detail="仅支持 Excel (.xlsx) 或 CSV 文件，.xls 已不再支持")

    suffix = os.path.splitext(file.filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    from fastapi_app.tasks.batch_tasks import batch_import_stockins_task
    task = batch_import_stockins_task.delay(tmp_path, file.filename, user_id=current_user.id)

    return {
        "success": True,
        "message": "批量导入任务已提交",
        "task_id": task.id,
        "status_url": f"/api/v1/tasks/status/{task.id}",
    }


# ==================== 报表导出（异步） ====================

@router.post("/export-report")
async def async_export_report(
    request: ReportExportRequest,
    current_user: User = Depends(require_permission("batch_import")),
):
    """异步导出报表（提交后台任务）"""
    if request.report_type not in ("order", "stockin", "stockout", "deduction"):
        raise HTTPException(status_code=400, detail=f"不支持的报表类型: {request.report_type}")

    from fastapi_app.tasks.report_tasks import export_report_task

    filters = {
        "customer": request.customer,
        "product": request.product,
        "status": request.status,
        "start_date": request.start_date,
        "end_date": request.end_date,
    }

    task = export_report_task.delay(request.report_type, filters, user_id=current_user.id)

    return {
        "success": True,
        "message": "报表导出任务已提交",
        "task_id": task.id,
        "status_url": f"/api/v1/tasks/status/{task.id}",
    }


# ==================== 导出文件下载 ====================

@router.get("/download/{task_id}")
async def download_task_result(
    task_id: str,
    current_user: User = Depends(require_permission("batch_import")),
):
    """下载异步任务生成的文件"""
    celery_app = _require_celery()
    result = celery_app.AsyncResult(task_id)

    if not result.ready():
        raise HTTPException(status_code=202, detail="任务尚未完成")

    if not result.successful():
        raise HTTPException(status_code=500, detail="任务执行失败")

    task_result = result.result
    file_path = task_result.get("file_path")

    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="导出文件不存在或已过期")

    from fastapi.responses import FileResponse
    filename = task_result.get("filename", "export.xlsx")

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
    except Exception:
        pass
