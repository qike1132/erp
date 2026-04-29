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

// 入库
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

// 出库
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

// 库存
export interface InventoryItem {
  product_id: number
  product_name: string
  barcode: string
  current_stock: number
  total_stockin: number
  total_stockout: number
  total_deducted: number
}

// 客户
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

// 供应商
export interface Supplier {
  id: number
  name: string
  contact_person?: string
  phone?: string
  address?: string
  remark?: string
  status?: string
}

// 采购订单
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
  items?: any[]
  materials?: any[]
}

// 审批
export interface ApprovalItem {
  id: number
  type: string
  ref_id: number
  summary: string
  status: string
  created_by: string
  created_at: string
}

// 用户
export interface User {
  id: number
  username: string
  isSuper: boolean
  permissions: string[]
}

// 导航
export interface NavSection {
  title: string
  items: NavItem[]
}

export interface NavItem {
  title: string
  path: string
  icon?: string
  permission?: string
}

// 权限
export interface PermissionItem {
  id: number
  code: string
  name: string
  parent_id: number | null
  children?: PermissionItem[]
}

// 分页结果
export interface PageResult<T> {
  items: T[]
  total: number
  page: number
  per_page: number
  total_pages?: number
}

// 产品
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
