"""仪表盘响应 Schema(从 services/dashboard_service.py 归位)"""
from pydantic import BaseModel


class DashboardStats(BaseModel):
    order_today: int = 0          # 今日订单商品总件数
    order_yesterday: int = 0      # 昨日订单商品总件数
    stockin_today: int = 0        # 今日备货商品总件数
    stockin_yesterday: int = 0    # 昨日备货商品总件数
    stockout_today: int = 0       # 今日出货商品总件数
    stockout_yesterday: int = 0   # 昨日出货商品总件数
    pending_approvals: int = 0
    low_stock_count: int = 0
    pending_purchases: int = 0
    pending_materials: int = 0
    production_completion_rate: float = 0.0
    pending_shipments: int = 0
    total_shipments_today: int = 0
    total_orders_today: int = 0

class DashboardResponse(BaseModel):
    success: bool = True
    data: DashboardStats | None = None

class Activity(BaseModel):
    type: str
    time: str
    status: str
    title: str
    desc: str


_CACHE_KEY_ACTIVITIES = "dashboard:activities"

class TodoItem(BaseModel):
    id: int = 0
    type: str = ""
    description: str = ""
    urgency: str = "normal"
    created_at: str = ""
    related_module: str = ""
    related_business_id: int = 0

class TodoListResponse(BaseModel):
    success: bool = True
    data: list[TodoItem] = []

class SystemStatus(BaseModel):
    is_running: bool = True
    last_sync_time: str = ""
    data_status: str = "up_to_date"

class SystemStatusResponse(BaseModel):
    success: bool = True
    data: SystemStatus | None = None

class NavItem(BaseModel):
    id: int
    name: str
    code: str
    icon: str | None = None
    url: str
    permission_codes: list[str] = []

class NavSection(BaseModel):
    name: str
    items: list[NavItem] = []

class CustomerOutDetail(BaseModel):
    customer_name: str = ""
    total_quantity: int = 0
    total_amount: float = 0.0

class CustomerOutDetailResponse(BaseModel):
    success: bool = True
    data: list[CustomerOutDetail] = []

class MobileStockData(BaseModel):
    today_quantity: int = 0
    today_amount: float = 0.0
    month_quantity: int = 0
    month_amount: float = 0.0
    total_quantity: int = 0
    total_amount: float = 0.0

class MobileDeptData(BaseModel):
    name: str = ""
    daily_output: int = 0
    output_value: float = 0.0

class MobileProductionData(BaseModel):
    total_value: float = 0.0
    departments: list[MobileDeptData] = []

class MobileShippingData(BaseModel):
    daily_qty: int = 0
    total_amount: float = 0.0

class MobileOrderData(BaseModel):
    daily_qty: int = 0
    daily_amount: float = 0.0
    total_amount: float = 0.0
    total_qty: int = 0
    total_inventory: int = 0
    total_inventory_amount: float = 0.0

class MobileWarehouseData(BaseModel):
    in_qty: int = 0
    in_amount: float = 0.0
    out_qty: int = 0
    out_amount: float = 0.0

class MobileDashboardData(BaseModel):
    stock: MobileStockData
    production: MobileProductionData
    shipping: MobileShippingData
    orders: MobileOrderData
    warehouse: MobileWarehouseData
    production_plans: dict = {}

class MobileDashboardResponse(BaseModel):
    success: bool = True
    data: MobileDashboardData | None = None

