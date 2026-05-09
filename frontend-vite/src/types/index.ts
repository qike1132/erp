export interface ApiResponse<T = unknown> {
  success: boolean
  data?: T
  detail?: string
  message?: string
  status_code?: number
  order?: T
  orders?: T[]
  total?: number
  html?: string
  task_id?: string
  filename?: string
  total_rows?: number
  total_upserted?: number
  summary?: T
  tables?: T
  backups?: T
  names?: T
  products?: T
  registrations?: T
  pages?: number
}

/** 分页结果，与后端 PaginatedResponse 对齐 */
export type PageResult<T> = PaginatedResponse<T>

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  pages: number
  current_page: number
  next_cursor?: string | number
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
  is_locked?: boolean
  locked_by_name?: string
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
  current_stock: number
  total_stockin: number
  total_stockout: number
  total_deducted: number
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
  status?: string
  created_at?: string
}

export interface PurchaseOrderItem {
  id: number
  product_name: string
  barcode: string
  material_name: string
  material_category?: string
  specification?: string
  quantity: number
  unit: string
  unit_price: number
  total_price: number
  supplier_name: string
  customer_name: string
  remark: string
}

export interface PurchaseOrder {
  id: number
  order_no: string
  status: string
  customer_name: string
  supplier_name: string
  remark?: string
  create_time: string
  order_date: string
  total_quantity?: number
  total_amount?: number
  item_count?: number
  source_order_no?: string
  items?: PurchaseOrderItem[]
  materials?: PurchaseOrderItem[]
}

export interface UnprocessedOrder {
  id: number
  order_no: string
  customer: string
  product_name: string
  barcode?: string
  quantity: number
  order_date: string
  status: string
  product?: Product
  has_bom?: boolean
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
  isSuper: boolean
  permissions: string[]
  password?: string
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
  productId: string
  productName: string
  customer: string
  date: string
  quantity: number
  note?: string
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
