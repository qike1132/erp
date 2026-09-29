"""编号巡检只读端点（spec §4.5 拉取式暴露）。

ARQ cron 周期把巡检结果写入 numbering_audit，本端点只读最近若干轮，
不做任何写入。认证由 api/v1/router.py 注册处的依赖统一施加。
"""
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_read_db
from fastapi_app.shared_models import NumberingAudit

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get('')
async def latest_audit(
    limit: int = Query(200, ge=1, le=1000, description='返回最近多少条巡检记录'),
    db: AsyncSession = Depends(get_async_read_db),
) -> dict:
    """返回最近一轮（按时间倒序前 limit 条）编号巡检记录。"""
    rows = (await db.execute(
        select(NumberingAudit)
        .order_by(NumberingAudit.checked_at.desc(), NumberingAudit.id.desc())
        .limit(limit)
    )).scalars().all()
    return {
        'items': [
            {
                'scope': r.scope,
                'counter_behind': bool(r.counter_behind),
                'detail': r.detail,
                'checked_at': r.checked_at.isoformat(),
            }
            for r in rows
        ]
    }
