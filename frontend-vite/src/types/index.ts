// ===== 基础 API 响应类型 =====

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
}

/** 用户信息（登录响应内嵌） */
export interface UserInfo {
  user_id: number
  id?: number
  username: string
  is_super: boolean
  permissions: string[]
}

/** 订单明细（SKU 粒度），对应后端 OrderItemSchema */
export interface OrderSKU {
  id: number
  order_id: number
  product_id: number
  product_name: string | null
  product_barcode: string | null
  quantity: number
  order_type: string
  country: string | null
  deduct_stock: boolean
  deduct_quantity: number
  note: string | null
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
  order_type?: string
  country?: string
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

export interface StockOutRecord {
  id: number
  stockout_no: string
  product_name: string
  product_id: number
  barcode?: string
  quantity: number
  deducted?: boolean
  customer: string
  stockout_date: string
  status: string
  note?: string
  order_type?: string
  country?: string
}

export interface InventoryItem {
  product_id: number
  product_name: string
  barcode: string
  product_barcode?: string
  customer?: string
  current_stock: number
  total_stockin: number
  total_stockout: number
  total_deducted: number
  stockin_qty?: number
  has_stockin?: number
  direct_stockout_qty?: number
  regular_stockout_qty?: number
  custom_stockout_qty?: number
  regular_order_qty?: number
  custom_order_qty?: number
  has_order?: number
  country_data?: string
  order_quantity?: number
  stockin_quantity?: number
  total_stock?: number
  available_stock?: number
  country_orders?: Record<string, number>
  available_stock_by_country?: Record<string, number>
  _custom_details?: { country: string; qty: number }[]
  _country_available?: { country: string; qty: number }[]
}

/** 后端 /stock/inventory 响应结构（InventoryResponse schema） */
export interface InventoryResponse {
  success: boolean
  data: InventoryItem[]
  total_order_quantity: number
  total_stockin_quantity: number
  total_stock: number
  total_available_stock: number
  all_countries: string[]
  all_customers: string[]
  total_items: number
  page: number
  per_page: number
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
  order_type?: string
  country?: string
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
  order_type?: string
  country?: string
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
}

export interface UserCreate {
  username: string
  password: string
  is_super?: boolean
}

export interface NavSection {
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

export interface Product {
  id: number
  name: string
  barcode?: string
  customer?: string
  category?: string
  unit?: string
  note?: string
  status?: boolean
  price?: number
  image?: string
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

export interface DailyProductionRecord {
  id: number
  department: string
  product_id?: number | null
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
  regular_available?: number
  custom_available?: number
}

export interface StagedStockout {
  id: number
  product_id: string
  product_name: string
  customer: string
  date: string
  quantity: number
  note?: string
  order_type?: string
  country?: string
}

export interface StockoutRecordGroup {
  date: string
  expanded: boolean
  records: StockOutRecord[]
  totalQty: number
  summaryList: StockoutRecordSummary[]
}

export interface StockoutRecordSummary {
  key: string
  firstId: number
  customer: string
  productName: string
  productImage?: string
  barcode?: string
  quantity: number
  deductQuantity: number
  notesDisplay?: string
}

export interface StockoutBatchSubmit {
  product_id: number
  customer: string
  quantity: number
  stockout_date: string
  note?: string
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

export interface BatchQueryItem {
  id: number
  order_no: string
  customer: string
  order_date: string | null
  product_id: number
  product_name: string | null
  product_barcode: string | null
  quantity: number
  deducted_qty: number
  shipped_qty: number
  status: string | null
  computed_status: string | null
  batch_no: string | null
  batch_completed_at: string | null
  is_locked: boolean | null
  record_type?: string  // 'order' or 'stockin'
}

export interface BatchNoUpdatePayload {
  batch_no: string | null
  sync_same_batch?: boolean
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

export interface BackupScheduleTask {
  name: string
  task: string
  schedule: string
  enabled: boolean
  last_run?: string | null
  last_status?: string | null
}

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
