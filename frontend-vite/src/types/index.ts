export interface ApiResponse<T = unknown> {
  success: boolean
  data?: T
  detail?: string
  status_code?: number
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  pages: number
  current_page: number
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
