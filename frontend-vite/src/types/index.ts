import type { BatchImportResult as GenBatchImportResult, FinishedStockItem as GenFinishedStockItem, UserCreate as GenUserCreate, BatchQueryItem as GenBatchQueryItem, InventoryResponse as GenInventoryResponse, ProductionRecordListResponse as GenProductionRecordListResponse, UserUpdate as GenUserUpdate, BackupScheduleTask as GenBackupScheduleTask, OneClickGenerateRequest as GenOneClickGenerateRequest, MissingBomProduct as GenMissingBomProduct } from '@/types/api'
// ===== 基础 API 响应类型 =====

/**
 * 把生成层（@/types/api）里可选、但后端实际必发的字段断言为必填。
 *
 * 用于替代「整份重抄一遍字段清单」的手写 DTO：字段名与类型仍以生成层为唯一真相，
 * 手写层只保留「这几个字段一定存在」这一条口径断言。后端改字段名时 Pick<T, K> 直接报错。
 *
 * 注意 `Required<Pick<…>>` 不能简写成 `Pick<…>`：Pick 会**保留** `?` 修饰符，
 * 断言会静默失效（vue-tsc 里表现为消费方拿到 `number | undefined`）。
 */
export type WithRequired<T, K extends keyof T> = Omit<T, K> & Required<Pick<T, K>>

/**
 * 信封/记录派生形式：字段清单仍取生成层，只把某个字段的类型换成本地定义
 * （数组元素加强、可空收窄、或换成前端视图类型）。
 *
 * 不能直接写 `Required<生成层信封>`：生成层信封引用的是生成层元素（全可选镜像），
 * Required<> 只去掉信封自身的 `?`，元素口径反而变松。
 * 也不能写成 `… & { items: X[] }`：等号右侧一出现花括号，就等于把字段清单抄了第二遍，
 * check-mobile-dto 的「派生别名放行」判据（右侧不含 `{`）正是拦这个的。
 */
export type ReplaceField<T, K extends keyof T, V> = Omit<T, K> & Record<K, V>

/** 覆盖字段并要求整份必填：WithField<T,K,V> === Required<ReplaceField<T,K,V>> */
export type WithField<T, K extends keyof T, V> = Required<ReplaceField<T, K, V>>

/** 数组字段的简写：WithItems<T, K, E> === WithField<T, K, E[]> */
export type WithItems<T, K extends keyof T, E> = WithField<T, K, E[]>

/**
 * 只取生成层里前端确实在用的那几个字段，并把它们断言为必填。
 *
 * 用于「后端模型字段比前端消费的更多」的手写 DTO：抄字段清单会连类型一起抄第二份，
 * 而 Pick 只抄名字——后端加字段不需要同步前端，改名/删字段则直接编译报错。
 * 不能顺手写 Required<生成层>：那会替前端**没用的**字段也发出「一定存在」的断言。
 */
export type PickRequired<T, K extends keyof T> = Required<Pick<T, K>>

/** 通用 API 响应（精简版，仅保留通用字段） */
export interface ApiResponse<T = unknown> {
  success: boolean
  data?: T
  detail?: string
  message?: string
  status_code?: number
}

/** 分页响应（含分页元数据） */
export interface PaginatedResponse<T> {
  items: T[]
  total: number
  pages: number
  current_page: number
  next_cursor?: string | number
}

/** 分页结果，与后端 PaginatedResponse 对齐 */
export type PageResult<T> = PaginatedResponse<T>

/** 登录响应 */
export interface LoginResponse {
  success: boolean
  access_token: string
  token_type: string
  /** 登录接口直接返回的用户信息（避免登录后再发 GET /auth/me） */
  user?: UserInfo
}

/** 异步任务响应 */
export interface TaskResponse {
  success: boolean
  task_id: string
}

/** 导出/下载响应 */
export interface ExportResponse {
  success: boolean
  filename: string
  html?: string
  message?: string
}

/** 用户信息（登录响应内嵌） */
export interface UserInfo {
  user_id: number
  id?: number
  username: string
  is_super: boolean
  permissions: string[]
  /** 所属工厂：东莞/湖北/NULL（跨厂管理员为 null） */
  factory?: string | null
}

/** 订单明细（SKU 粒度），对应后端 OrderItemSchema */
export interface OrderSKU {
  id: number
  order_id: number
  product_id: number
  product_name: string | null
  product_barcode: string | null
  quantity: number
  deduct_stock: boolean
  deduct_quantity: number
  note: string | null
  has_processes?: boolean
  /** 该 SKU 的产品图片路径（后端 beile-list 注入，空串表示无图） */
  product_image?: string | null
  /**
   * ===== 方案 C：逐 SKU 下单量快照（后端 /orders/beile-list 注入）=====
   * 该 SKU 维度的实际下单数量（同一 SKU 拆多供应商时取 MAX）；无逐 SKU 快照时为 null。
   */
  purchase_order_qty?: number | null
  /** 该 SKU 维度的备品数量（生产数量的计算输入）；无逐 SKU 快照时为 null。 */
  spare_quantity?: number | null
  /** 该 SKU 维度是否已下单：有逐 SKU 快照以快照为准，否则回退订单级 is_ordered。 */
  is_ordered?: boolean
  /**
   * 逐 SKU 字段来源：
   * - 'po_sku' = 命中 purchase_order_sku 逐 SKU 快照（方案 C，可展示该 SKU 真实下单量/生产量）；
   * - 'order_level' = 未迁移 / 历史未回填 / 该 SKU 未被采购单覆盖，降级为订单级口径。
   */
  per_sku_source?: 'po_sku' | 'order_level'
}

export interface OrderItem {
  id: number
  product_name: string
  product_id: number
  barcode?: string
  quantity: number
  deduct_quantity: number
  deduct_stock: boolean
  order_date: string
  note: string
  status: string
  /**
   * 订单编号（后端 Order.order_no，列表接口 LIST_CONFIG 返回）。
   * 2026-10-17 审计 F1-3：此前共享类型缺这三个字段，移动端只能自己抄一份内联 DTO，
   * 于是「订单号/客户名」在移动端恒为空（10-14 order_no 事故的前端面）。
   */
  order_no?: string
  /** 客户名称（后端 Order.customer） */
  customer?: string
  /** 产品对象（列表接口 include_product=True 时返回 { id, name, barcode, image }） */
  product?: { id?: number; name?: string; barcode?: string; image?: string }
  is_locked?: boolean
  locked_by_name?: string
  /** 主订单下的 SKU 明细列表（多 SKU 聚合时 >1） */
  items?: OrderSKU[]
}

export interface StockInRecord {
  id: number
  stockin_no: string
  product_name: string
  product_id: number
  barcode?: string
  quantity: number
  deducted?: boolean
  customer: string
  stockin_date: string
  status: string
  note?: string
}

export interface InventoryItem {
  product_id: number
  product_name: string
  /** 后端不返回 barcode/current_stock（2026-10-18 OCR 评审修正），保留可选兼容旧夹具 */
  barcode?: string
  product_barcode?: string
  customer?: string
  current_stock?: number
  total_stockin: number
  total_stockout: number
  total_deducted: number
  stockin_qty?: number
  has_stockin?: number
  direct_stockout_qty?: number
  has_order?: number
  // 以下派生量后端把 0 值序列化成空串（见 stock_inventory_service._format_inventory_rows），
  // 故类型含 ''；展示层需按「空/0 → —」处理，不能直接当数字用
  order_quantity?: number | ''
  stockin_quantity?: number | ''
  total_stock?: number | ''
  available_stock?: number | ''
  /** 库存（结余）= 包装部入库 − 已出货；0 与负数都原样输出，不是空值 */
  inventory_balance?: number
}

/** 后端 /stock/inventory 响应结构（InventoryResponse schema） */
export type InventoryResponse = WithItems<Required<GenInventoryResponse>, 'data', InventoryItem>

export type FinishedStockItem = Required<GenFinishedStockItem>
// image 是原图 URL（已出站签名），点击缩略图预览用它；image_thumb 是确定性后缀派生的列表缩略图，列表 img 用它；
// remark 是本页备注，按「客户+产品+批次」一行一条，由页面自己维护

export interface FinishedStockSummary {
  success: boolean
  data: FinishedStockItem[]
  total: number
  /** 过滤后全量（非当前页）的可用库存合计 */
  total_available: number
  page: number
  per_page: number
  all_customers: string[]
}

export interface BatchAvailable {
  batch_no: string
  available_quantity: number
}

export interface Customer {
  id: number
  customer_code?: string
  name: string
  contact?: string
  phone?: string
  address?: string
  note?: string
  status: boolean
  create_time?: string
}

export interface Supplier {
  id: number
  name: string
  contact_person?: string
  phone?: string
  address?: string
  remark?: string
  status?: boolean
  created_at?: string
}

export interface PurchaseOrderItem {
  id: number
  product_name?: string
  barcode?: string
  material_name: string
  /** 后端 _serialize_po_item 返回 material_code */
  material_code?: string
  /** 后端返回 category（material_category 为兼容字段） */
  material_category?: string
  category?: string
  specification?: string
  quantity: number
  /** 逐行损耗率快照（千分之几）；缺失时回退订单级 spare_rate（后端 get_purchase_order 下发） */
  loss_rate?: number | null
  unit?: string
  unit_price?: number
  total_price?: number
  /** 后端 _serialize_po_item 返回 amount */
  amount?: number
  supplier_name?: string
  customer_name?: string
  remark?: string
}

export interface PurchaseOrderSkuItem {
  product_name: string
  barcode: string
  quantity: number
}

export interface PurchaseOrder {
  id: number
  order_no: string
  status: string
  customer_name: string
  supplier_name: string
  /** 后端 get_purchase_order 返回 note（与 remark 同义） */
  remark?: string
  note?: string
  create_time: string
  order_date: string
  total_quantity?: number
  total_amount?: number
  item_count?: number
  source_order_no?: string
  items?: PurchaseOrderItem[]
  materials?: PurchaseOrderItem[]
  sku_items?: PurchaseOrderSkuItem[]
  product_name?: string
  quantity?: number
  /** 订单级损耗率快照（千分之几）；后端 get_purchase_order 下发，物料清单的数量回退口径 */
  spare_rate?: number | null
  completed_at?: string
  supplier_id?: number
  customer?: string
}

export interface UnprocessedOrderItem {
  id: number
  product_id: number
  product_name: string
  product_barcode?: string | null
  quantity: number
  deduct_quantity?: number
  note?: string
  has_bom?: boolean
}

export interface UnprocessedOrder {
  id: number
  composite_id: string
  order_no: string
  customer: string
  product_name: string
  barcode?: string
  quantity: number
  order_date: string
  status: string
  product?: Product
  has_bom?: boolean
  create_time?: string
  record_type?: 'order' | 'stockin'
  items?: UnprocessedOrderItem[]
  sku_count?: number
  source_order_id?: number
  product_id?: number | null
  customer_name?: string
}

export type OneClickGenerateRequest = GenOneClickGenerateRequest

export interface GeneratedOrderRef {
  id: number
  order_no: string
  status?: string
}

export type MissingBomProduct = GenMissingBomProduct

export type OneClickGenerateCode = 'OK' | 'MISSING_BOM' | 'SOURCE_INVALID'

export interface OneClickGenerateResponse {
  success: boolean
  message?: string
  code?: OneClickGenerateCode
  created_count: number
  idempotent: boolean
  orders: GeneratedOrderRef[]
  missing_bom: MissingBomProduct[]
}

export interface ApprovalItem {
  id: number
  order_id: number
  order_no: string | null
  requester_id: number
  requester_name: string | null
  operation_type: string
  operation_type_display: string
  operation_data: string | null
  status: string
  status_display: string
  request_time: string | null
  approver_id: number | null
  approver_name: string | null
  approval_time: string | null
  rejection_reason: string | null
  lock_time: string | null
}

export interface User {
  id: number
  username: string
  is_super?: boolean
  status?: boolean
  create_time?: string
  permissions: string[]
  /** 所属工厂：东莞/湖北/NULL（跨厂管理员为 null） */
  factory?: string | null
  /** 所属部门：生产部/仓库/业务部/采购部/NULL */
  department?: string | null
}

export type UserCreate = GenUserCreate
// factory（东莞/湖北）与 department（生产部/仓库/业务部/采购部）：空字符串表示清除

export type UserUpdate = Partial<WithField<WithField<GenUserUpdate, 'password', string>, 'is_super', boolean>> // password 不修改则不传；factory/department 传空字符串表示清除

export interface NavSection {
  /** section_key，用于权限选择模块与导航栏建立关联 */
  key?: string
  title: string
  items: NavItem[]
}

export interface NavItem {
  title: string
  path: string
  icon?: string
  permission?: string
  permissionCodes?: string[]
}

export interface PermissionItem {
  id: number
  code: string
  name: string
  parent_id: number | null
  icon?: string
  url?: string
  section?: string
  section_name?: string
  sort_order?: number
  is_nav?: boolean
  children?: PermissionItem[]
}

export interface ProductCustomerRef {
  id: number
  name: string
}

export interface Product {
  id: number
  name: string
  barcode?: string
  /**
   * 所属客户（多对多）。
   * 空数组 = 未挂客户 = **对所有客户可见**（兼容存量 SKU 的口径）。
   * 后端字段名 customers；提交时用 customer_ids（见 productApi.create/update）。
   */
  customers?: ProductCustomerRef[]
  category?: string
  unit?: string
  note?: string
  status?: boolean
  price?: number
  image?: string
  /** 列表缩略图（后端出站派生；缺失时前端回退 image） */
  image_thumb?: string
  /** 预览弹窗用原图（后端出站派生；找不到原图时回退 image） */
  image_original?: string
  /** 规格型号 */
  specification?: string
  /** 所属工厂：东莞/湖北 */
  factory?: string
}

export interface ProductionCraft {
  id: number
  product_name?: string
  barcode?: string
  quantity?: number
  status?: string
  year?: number
  month?: number
}

/** 生产三车间（后端 PRODUCTION_DEPARTMENTS 的键） */
export type ProductionDepartment = 'filling' | 'handcraft' | 'packaging'

export interface DailyProductionRecord {
  id: number
  department: string
  product_id?: number | null
  customer_id?: number | null
  customer_name?: string | null
  product_name: string
  barcode: string
  unit_price: number
  quantity: number
  production_value: number
  production_date: string
  remark?: string | null
  create_time?: string | null
  created_by?: string | null
}

export interface ProductionRecordStats {
  total_quantity: number
  total_value: number
  total_sku: number
}

/** GET /daily-production/records 的响应体（`get<T>` 不拆 { data }，data 是顶层字段） */
export type ProductionRecordListResponse = WithField<WithItems<GenProductionRecordListResponse, 'data', DailyProductionRecord>, 'stats', ProductionRecordStats> // 后端 get_records 始终构造 stats（无记录时全 0），故断言非 null

/** 明细抽屉的查询参数。year/month 与 start_date/end_date 二选一，区间优先。 */
export interface RecordsQuery {
  year?: number
  month?: number
  start_date?: string
  end_date?: string
  /**
   * 部门筛选。刻意保持 string 而非收窄成 ProductionDepartment：
   * 抽屉的部门下拉选项直接来自接口响应的 DepartmentSummary.department（string），
   * 选中后回填到这个字段 —— 收窄就得在那个边界加 cast，或把响应模型改错。
   * 非法值由后端按 scope 过滤，前端不做这层类型约束。
   */
  department?: string
  created_by?: string
  /** 产品名或 69 码关键词；发送前 trim，空串省略键（后端把空串当"等于空"） */
  keyword?: string
  sort?: 'asc' | 'desc'
  page?: number
  per_page?: number
  production_date?: string
}

export interface TrendDay {
  date: string
  filling: number
  handcraft: number
  packaging: number
  total: number
}

/** GET /daily-production/trend 的响应体。departments 只含当前用户可见部门。 */
export interface TrendResponse {
  success: boolean
  start_date: string
  end_date: string
  departments: string[]
  days: TrendDay[]
}

export interface DepartmentSummary {
  department: string
  department_label: string
  total_quantity: number
  total_value: number
  sku_count: number
}

export interface DailySummary {
  date: string
  departments: DepartmentSummary[]
  overall_quantity: number
  overall_value: number
  overall_sku_count: number
}

export interface MonthlyDayData {
  date: string
  day: number
  filling: { quantity: number; value: number; sku_count: number }
  handcraft: { quantity: number; value: number; sku_count: number }
  packaging: { quantity: number; value: number; sku_count: number }
  total: { quantity: number; value: number; sku_count: number }
}

export interface MonthlySummary {
  year: number
  month: number
  daily_data: MonthlyDayData[]
  monthly_departments: DepartmentSummary[]
  monthly_total_quantity: number
  monthly_total_value: number
}

export interface MaterialRegistration {
  id: number
  purchase_order_id?: number
  purchase_order_no?: string
  supplier_id?: number
  supplier_name?: string
  status?: string
  created_at?: string
}

export interface StagingOrder {
  id: number
  product_name: string
  barcode?: string
  quantity: number
  customer?: string
}

/**
 * 暂存区条目（后端 `StagingOrder` / `StagingStockIn` / `StagingStockOut` 的 `to_dict()` 实际字段）。
 *
 * ⚠️ 列表接口返回的是**扁平行**；三种暂存实体的日期字段名不同：
 * 订单 `order_date`、备货 `stockin_date`、出货 `stockout_date`。
 */
export interface StagingRow {
  id: number
  customer: string
  product_id: number | null
  product_name: string
  product_barcode: string
  quantity: number
  note: string
  status: string
  is_validated: boolean
  validation_error: string
  created_at: string
  /** 订单暂存专用 */
  order_date?: string
  /** 备货暂存专用 */
  stockin_date?: string
  /** 出货暂存专用 */
  stockout_date?: string
  deduct_stock?: boolean
  deduct_quantity?: number
  import_batch_id?: string
}

/**
 * 暂存区列表响应（后端 `schemas/staging.py::StagingListResponse`）。
 *
 * ⚠️ 条目挂在 **`data`** 上，且**不是** `items` / `staging_orders` / `staging_stockins`。
 * 三个列表端点（`/staging-orders`、`/staging-stockins`、`/staging-stockouts`）契约一致。
 * （2026-09-18：customer-order 导入后列表恒空，即为误读为 `staging_orders` 所致。）
 */
export interface StagingListResponse<T = StagingRow> {
  success: boolean
  data: T[]
  total: number
}

/**
 * 暂存区导入结果（后端 `StagingOrderImportResult` / `StagingStockInImportResult` /
 * `StagingStockOutImportResult`，三者字段一致）。
 *
 * 字段为可选：调用方按"防御式读取"消费（后端返回 `success:false` 时仍是 HTTP 200，
 * 必须显式判 `success`，不能只看 HTTP 状态码）。
 */
export interface StagingImportResult {
  success?: boolean
  message?: string
  imported?: number
  session_id?: string
  errors?: string[]
}

/**
 * 批量导入结果（后端 `schemas/batch.py::BatchImportResult`）。
 *
 * 用于 `/batch/batch-import`、`/batch/import-orders`、`/batch/import-stockins` 等 Excel 导入端点。
 * 注意与 `StagingImportResult` 区分：本类型**不含** `errors` 明细，而多出 `skipped`。
 */
export type BatchImportResult = Required<GenBatchImportResult>

export interface ShipmentRecord {
  id: number
  plan_id: number
  product_name: string
  quantity: number
  shipped_at?: string
}

export interface QueryParams {
  page?: number
  per_page?: number
  keyword?: string
  status?: string
  sort_by?: string
  sort_order?: string
  [key: string]: unknown
}

export interface ShipmentInfo {
  order_quantity: number
  shipped_quantity: number
  available_quantity: number
}

export interface StagedStockout {
  id: number
  product_id: string
  product_name: string
  customer: string
  date: string
  quantity: number
  note?: string
  /** 成品库存批次号（选填；指定则按该批次扣减） */
  batch_no?: string
}

export interface StockoutBatchSubmit {
  product_id: number
  customer: string
  quantity: number
  stockout_date: string
  note?: string
  batch_no?: string | null
}

export interface OrderBatchItem {
  id: number
  order_no: string
  customer: string
  order_date: string | null
  product_id: number
  product_name: string | null
  quantity: number
  status: string | null
  batch_no: string | null
  batch_completed_at: string | null
  is_locked: boolean | null
}

export type BatchQueryItem = WithRequired<GenBatchQueryItem, 'order_date' | 'product_name' | 'product_barcode' | 'deducted_qty' | 'shipped_qty' | 'status' | 'computed_status' | 'batch_no' | 'batch_completed_at' | 'is_locked'>

export interface BatchNoUpdatePayload {
  batch_no: string | null
  sync_same_batch?: boolean
  record_type?: 'order' | 'stockin'
}

export interface BatchAssignPayload {
  order_ids: number[]
  batch_no: string
}

export interface BatchCompletePayload {
  batch_no: string
}

export interface ApprovalListResult {
  success: boolean
  data: ApprovalItem[]
  total: number
  pending_count: number
  approved_count: number
  rejected_count: number
}

export interface Registration {
  id: number
  purchase_order_id?: number
  purchase_order_no?: string
  supplier_id?: number
  supplier_name?: string
  status?: string
  created_at?: string
  items?: RegistrationItem[]
  update_time?: string
  customer_name?: string
  product_name?: string
  product_quantity?: number
  progress?: number
  total_ordered?: number
  total_received?: number
  remark?: string
}

export interface RegistrationItem {
  id: number
  material_name: string
  specification?: string
  material_category?: string
  ordered_quantity: number
  received_quantity: number
  unit?: string
  remark?: string
  progress?: number
}

export interface OrderPreview {
  id: number
  purchase_order_no: string
  supplier_name: string
  customer_name: string
  product_name: string
  product_quantity: number
  items: RegistrationItem[]
  status: string
  progress: number
  total_ordered: number
  total_received: number
  update_time?: string
  source_orders?: { id: number; order_no: string; customer_name?: string; product_name?: string; quantity?: number }[]
  item_count?: number
  order_date?: string
}

// ===== 备份系统 =====
export interface BackupRecord {
  id: number
  type: string
  trigger_type: string
  filename: string | null
  size: number | null
  table_count: number | null
  total_rows: number | null
  operator: string | null
  remark: string | null
  status: string
  error_message: string | null
  duration_seconds: number | null
  ip_address: string | null
  user_agent: string | null
  parent_record_id: number | null
  created_at: string | null
  updated_at: string | null
}

export type BackupScheduleTask = ReplaceField<Pick<GenBackupScheduleTask, 'name' | 'task' | 'schedule' | 'enabled' | 'last_run' | 'last_status'>, 'enabled', boolean> // 只取前端消费的 6 个字段：enabled 后端恒发故必填，last_run/last_status 允许缺省

export interface BackupStatus {
  success: boolean
  backup_dir: string
  total_backups: number
  total_size_bytes: number
  last_full_backup: {
    filename: string
    size: number
    exported_at: string
    exported_by: string
    remark: string
    type: string
    table_count: number
    total_rows: number
  } | null
  checksum_tables: string[]
  timestamp: string
}
