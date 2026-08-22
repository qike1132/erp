"""仪表盘统计服务(对外兼容入口)

从 dashboard_service.py 按主题拆分为 services/dashboard/ 子包,
Schema 归位 schemas/dashboard.py。
- stats: 核心统计  - activities: 动态  - todos: 待办
- nav: 导航/系统状态  - customer: 客户维度  - mobile: 移动端看板

本文件保留全部对外符号的 re-export,历史调用方
`from fastapi_app.services.dashboard_service import X` 保持不变。
"""
from fastapi_app.schemas.dashboard import (  # noqa: F401
    Activity,
    CustomerOutDetail,
    CustomerOutDetailResponse,
    DashboardResponse,
    DashboardStats,
    MobileDashboardData,
    MobileDashboardResponse,
    MobileDeptData,
    MobileOrderData,
    MobileProductionData,
    MobileShippingData,
    MobileStockData,
    MobileWarehouseData,
    NavItem,
    NavSection,
    SystemStatus,
    SystemStatusResponse,
    TodoItem,
    TodoListResponse,
)
from fastapi_app.services.dashboard.activities import (  # noqa: F401
    _get_cached_activities,
    _set_cached_activities,
    fetch_dashboard_activities,
)
from fastapi_app.services.dashboard.customer import (  # noqa: F401
    _parse_dashboard_date,
    fetch_customer_order_details,
    fetch_customer_out_details,
)
from fastapi_app.services.dashboard.mobile import (  # noqa: F401
    fetch_mobile_dashboard,
)
from fastapi_app.services.dashboard.nav import (  # noqa: F401
    fetch_nav_sections,
    fetch_system_status,
)
from fastapi_app.services.dashboard.stats import (  # noqa: F401
    _fetch_independent_stats,
    _get_mv_daily_quantity,
    _mv_or_base,
    _query_production_stats,
    _query_today_yesterday_base,
    _query_today_yesterday_base_with_mv,
    _resolve_yesterday_from_mv,
    fetch_dashboard_stats,
)
from fastapi_app.services.dashboard.todos import (  # noqa: F401
    fetch_dashboard_todos,
)
