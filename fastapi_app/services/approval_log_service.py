"""
审批日志服务

从 approval_service.py 提取，消除 order_service → approval_service 循环依赖。
本模块为 order 领域与 approval 领域的共享工具层，单向依赖 shared_models。
"""
import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.shared_models import ApprovalLog, ApprovalRequest, User

logger = logging.getLogger(__name__)


async def create_approval_log(db: AsyncSession, approval_request: ApprovalRequest, action: str,
                              actor: User, details: dict | None = None):
    """创建审批日志记录"""
    log = ApprovalLog(
        approval_request_id=approval_request.id,
        action=action,
        actor_id=actor.id,
        actor_name=actor.username,
        details=json.dumps(details, ensure_ascii=False) if details else None,
    )
    db.add(log)
