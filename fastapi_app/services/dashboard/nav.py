"""仪表盘导航与系统状态

从 dashboard_service.py 按主题拆出,行为与原实现完全一致。
"""
import logging
from datetime import UTC, datetime

from fastapi_app.schemas.dashboard import SystemStatus, SystemStatusResponse

logger = logging.getLogger(__name__)


def fetch_system_status() -> SystemStatusResponse:
    """查询系统运行状态（当前为静态健康状态）。"""
    return SystemStatusResponse(
        success=True,
        data=SystemStatus(
            is_running=True,
            last_sync_time=str(datetime.now(UTC).date()),
            data_status="up_to_date",
        ),
    )

async def fetch_nav_sections():
    """查询导航菜单数据。"""
    from fastapi_app.core.nav_context import get_nav_sections_async
    return await get_nav_sections_async()