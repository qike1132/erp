import { get, post, put, del, upload, download } from './request'
import type {
  ApiResponse, User, OrderItem, Product, Customer, Supplier,
  PurchaseOrder, UnprocessedOrder, ApprovalItem, ApprovalListResult,
  NavSection, PermissionItem, StagingOrder,
  MaterialRegistration, Registration, OrderPreview, ProductionCraft, ShipmentRecord,
  InventoryItem, StockInRecord, StockOutRecord, ShipmentInfo,
  QueryParams, OrderBatchItem, BatchQueryItem, PaginatedResponse,
  BatchNoUpdatePayload, BatchAssignPayload, BatchCompletePayload,
} from '@/types'

// ===== 认证 =====
interface AuthMeResponse {
  user: { user_id: number; id?: number; username: string; is_super: boolean; permissions: string[] }
  user_id: number
  username: string
  is_super: boolean
  permissions: string[]
}
export const authApi = {
  login: (data: { username: string; password: string }) => post<{ access_token: string }>('/auth/login', data),
  logout: () => post('/auth/logout'),
  me: () => get<AuthMeResponse>('/auth/me'),
}

// ===== 订单 =====
export const orderApi = {
  list: (params?: QueryParams) => get<{ orders: OrderItem[]; total: number }>('/orders/list', params),
  detail: (id: number) => get<OrderItem>(`/orders/${id}`),
  create: (data: Partial<OrderItem>) => post<OrderItem>('/orders/create', data),
  update: (id: number, data: Partial<OrderItem>) => put<OrderItem>(`/orders/edit/${id}`, data),
  delete: (id: number) => del(`/orders/delete/${id}`),
  lock: (id: number) => post(`/orders/lock/${id}`),
  unlock: (id: number) => post(`/orders/unlock/${id}`),
  deductStock: (id: number) => post(`/orders/deduct-stock/${id}`),
  staging: {
    add: (data: Partial<StagingOrder>) => post<StagingOrder>('/staging-orders/add', data),
    list: () => get<StagingOrder[]>('/staging-orders/list'),
    delete: (id: number) => del(`/staging-orders/${id}`),
    confirm: () => post('/staging-orders/confirm'),
  },
}

// ===== 产品 =====
export const productApi = {
  list: (params?: QueryParams) => get<{ products: Product[]; total: number }>('/products/list', params),
  detail: (id: number) => get<Product>(`/products/${id}`),
  create: (data: Partial<Product>) => post<Product>('/products/create', data),
  update: (id: number, data: Partial<Product>) => put<Product>(`/products/edit/${id}`, data),
  delete: (id: number) => del(`/products/delete/${id}`),
  search: (q: string) => get<Product[]>('/products/search', { q }),
  bom: (productId: number, items: Record<string, unknown>[]) => post(`/products/bom/${productId}`, { items }),
  loadBom: (productId: number) => get<Record<string, unknown>>(`/purchase-center/product/${productId}/bom`),
  saveBom: (productId: number, bomData: Record<string, unknown>) => post(`/purchase-center/product/${productId}/bom`, bomData),
  searchProductsForBom: (keyword: string) => get<Product[]>('/purchase-center/products/search', { keyword }),
  bomPreview: (productId: number) => get<Record<string, unknown>>(`/purchase-center/products/${productId}/bom-preview`),
  copyBom: (targetProductId: number, sourceProductId: number, overwrite: boolean) =>
    post(`/purchase-center/products/${targetProductId}/copy-bom`, { source_product_id: sourceProductId, overwrite }),
}

// ===== 客户 =====
export const customerApi = {
  list: (params?: QueryParams) => get<{ customers: Customer[]; total: number }>('/customers/list', params),
  create: (data: Partial<Customer>) => post<Customer>('/customers/create', data),
  update: (id: number, data: Partial<Customer>) => put<Customer>(`/customers/edit/${id}`, data),
  toggleStatus: (id: number) => post(`/customers/toggle-status/${id}`),
  delete: (id: number) => del(`/customers/delete/${id}`),
  activeNames: () => get<{ id: number; name: string }[]>('/customers/active-names'),
}

// ===== 供应商 =====
export const supplierApi = {
  list: (params?: QueryParams) => get<{ suppliers: Supplier[]; total: number }>('/suppliers/list', params),
  create: (data: Partial<Supplier>) => post<Supplier>('/suppliers/create', data),
  update: (id: number, data: Partial<Supplier>) => put<Supplier>(`/suppliers/edit/${id}`, data),
  delete: (id: number) => del(`/suppliers/delete/${id}`),
  toggleStatus: (id: number) => post(`/suppliers/toggle-status/${id}`),
  search: (q: string) => get<Supplier[]>('/suppliers/search', { q }),
  activeNames: () => get<{ id: number; name: string }[]>('/suppliers/active-names'),
}

// ===== 库存 =====
export const stockApi = {
  stockins: (params?: QueryParams) => get<StockInRecord[]>('/stock/in/list', params),
  stockouts: (params?: QueryParams) => get<ApiResponse & { stockouts?: StockOutRecord[]; items?: StockOutRecord[]; total?: number }>('/stock/out/list', params),
  inventory: (params?: QueryParams) => get<InventoryItem[]>('/stock/inventory', params),
  deleteStockin: (id: number) => del(`/stock/in/delete/${id}`),
  deleteStockout: (id: number) => del(`/stock/out/delete/${id}`),
  searchProducts: (q: string) => get<ApiResponse & { products?: Product[] }>('/aux/product-search', { q }),
  availableShipment: (productId: number, customer: string) =>
    get<ApiResponse<ShipmentInfo>>('/aux/available-shipment', { product_id: productId, customer }),
  stagingStockins: {
    list: () => get<StagingOrder[]>('/staging-stockins'),
    add: (data: Partial<StagingOrder>) => post<StagingOrder>('/staging-stockins', data),
    delete: (id: number) => del(`/staging-stockins/${id}`),
    confirm: () => post('/staging-stockins/confirm'),
    clear: () => del('/staging-stockins/clear'),
    importExcel: (formData: FormData) => upload('/staging-stockins/import', formData),
  },
  stagingStockouts: {
    list: (sessionId?: string) => get<StagingOrder[]>('/staging-stockouts', sessionId ? { session_id: sessionId } : undefined),
    add: (data: Partial<StagingOrder>) => post<StagingOrder>('/staging-stockouts', data),
    delete: (id: number) => del(`/staging-stockouts/${id}`),
    confirm: (sessionId?: string) =>
      post('/staging-stockouts/confirm', sessionId ? { session_id: sessionId } : undefined),
    clear: (sessionId?: string) =>
      del(`/staging-stockouts/clear${sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ''}`),
    importExcel: (formData: FormData) => upload<ApiResponse & { session_id?: string; imported?: number; count?: number }>('/staging-stockouts/import', formData),
  },
  batchSubmitStockins: (stockins: Record<string, unknown>[]) => post('/aux/batch-submit-stockins', { stockins }),
  batchSubmitStockouts: (stockouts: Record<string, unknown>[]) => post('/aux/batch-submit-stockouts', { stockouts }),
  exportInventory: (params?: QueryParams) => download('/stock/export-inventory', '库存汇总.xlsx', params),
  downloadTemplate: () => download('/batch/download-template', '统一导入模板.xlsx'),
}

// ===== 采购 =====
export const purchaseApi = {
  orders: (params?: QueryParams) => get<{ orders: PurchaseOrder[]; total: number; pages: number; current_page: number }>('/purchase-center/orders', params),
  unprocessedOrders: (params?: { page?: number; per_page?: number }) => get<{ orders: UnprocessedOrder[]; total: number; pages: number; current_page: number }>('/purchase-center/unprocessed-orders', params),
  completeOrder: (id: number) => post(`/purchase-center/orders/complete`, { order_id: id }),
  batchComplete: (ids: number[]) => post('/purchase-center/orders/batch-complete', { ids }),
  deleteOrder: (id: number) => del(`/purchase-center/orders/${id}`),
  batchDelete: (ids: number[]) => post('/purchase-center/orders/batch-delete', { ids }),
  updateOrder: (id: number, data: Partial<PurchaseOrder>) => put(`/purchase-center/orders/${id}`, data),
  oneClickGenerate: (data: { order_ids: number[] }) => post<ApiResponse & { created_count: number; orders: { id: number; order_no: string }[] }>('/purchase-center/orders/one-click-generate', data),
  orderDetail: (id: number) => get<ApiResponse<PurchaseOrder>>(`/purchase-center/orders/${id}`),
  completed: (params?: QueryParams) => get<ApiResponse<PurchaseOrder[]> & { orders: PurchaseOrder[]; total: number; total_pages?: number; pages?: number }>('/purchase-center/orders/completed', params),
  exportCompleted: (params?: QueryParams) => post<ApiResponse & { html?: string }>('/purchase-center/orders/completed/export', params),
  quickFilters: () => get<ApiResponse & { quick_filters?: { id: string; name?: string; filters?: { start_date?: string; end_date?: string } }[] }>('/purchase-center/orders/completed/quick-filters'),
  suggestions: (field: string, q: string) => get<string[]>('/purchase-center/orders/completed/suggestions', { field, q }),
  factorySummary: (ids: number[]) => post<Record<string, unknown>>('/purchase-center/orders/factory-summary', { ids }),
  supplierSummary: (ids: number[]) => post<Record<string, unknown>[]>('/purchase-center/orders/supplier-summary', { ids }),
  saveFactoryEdits: (edits: Record<string, unknown>[]) => post('/purchase-center/orders/factory-summary/save', { edits }),
  summaryPrint: (ids: number[], format: string) => post<ApiResponse & { html?: string }>('/purchase-center/orders/summary-print', { ids, format }),
  supplierSummaryExport: (ids: number[]) => post('/purchase-center/orders/supplier-summary-export', { ids }),
  products: (params?: QueryParams) => get<Product[]>('/purchase-center/products', params),
  searchSuggestions: (q: string) => get<string[]>('/purchase-center/products/search-suggestions', { q }),
  calculate: (orders: Array<{ product_id: number; quantity: number }>) =>
    post<Record<string, unknown>>('/purchase-center/calculate', { orders }),
}

// ===== 审批 =====
export const approvalApi = {
  list: (params?: QueryParams) => get<ApprovalListResult>('/approvals/list', params),
  approve: (id: number) => post(`/approvals/approve/${id}`),
  reject: (id: number, reason: string) => post(`/approvals/reject/${id}`, { reason }),
}

// ===== 批次 =====
export const batchApi = {
  list: (params?: Record<string, unknown>) =>
    get<PaginatedResponse<BatchQueryItem>>('/order-batch/batch-query', params),
}

// ===== 物料 =====
export const materialApi = {
  overview: () => get<Record<string, unknown>>('/material-registrations/stats/overview'),
  trend: (days: number) => get<Record<string, unknown>>('/material-registrations/stats/trend', { days }),
  distribution: () => get<Record<string, unknown>>('/material-registrations/stats/distribution'),
  registrations: (params?: QueryParams) => get<ApiResponse<Registration[]> & { registrations: Registration[]; pages?: number; total_pages?: number }>('/material-registrations/registrations', params),
  registrationDetail: (id: number) => get<ApiResponse<Registration> & { registration?: Registration }>(`/material-registrations/registrations/${id}`),
  history: (params?: QueryParams) => get<ApiResponse<Registration[]> & { registrations: Registration[]; pages?: number; total_pages?: number }>('/material-registrations/history', params),
  receive: (id: number, data: { received_quantity: number; remark?: string }) => post<ApiResponse & { auto_completed?: boolean }>(`/material-registrations/items/${id}/receive`, data),
  purchaseOrderPreview: (orderNo: string) =>
    get<ApiResponse<OrderPreview> & { order?: OrderPreview }>(`/material-registrations/purchase-orders/preview/${encodeURIComponent(orderNo)}`),
  export: (params?: QueryParams) => post<ApiResponse & { html?: string }>('/material-registrations/export', params),
}

// ===== 生产 =====
export const productionApi = {
  craft: (params?: QueryParams) =>
    get<ProductionCraft[]>('/production-summary/craft/list', {
      year: new Date().getFullYear(),
      month: new Date().getMonth() + 1,
      ...params,
    }),
  createCraft: (data: Partial<ProductionCraft>) => post<ProductionCraft>('/production-summary/craft/create', data),
  editCraft: (id: number, data: Partial<ProductionCraft>) => put<ProductionCraft>(`/production-summary/craft/edit/${id}`, data),
  deleteCraft: (id: number) => del(`/production-summary/craft/delete/${id}`),
  packaging: (params?: QueryParams) =>
    get<ProductionCraft[]>('/production-summary/packaging/list', {
      year: new Date().getFullYear(),
      month: new Date().getMonth() + 1,
      ...params,
    }),
  createPackaging: (data: Partial<ProductionCraft>) => post<ProductionCraft>('/production-summary/packaging/create', data),
  editPackaging: (id: number, data: Partial<ProductionCraft>) => put<ProductionCraft>(`/production-summary/packaging/edit/${id}`, data),
  deletePackaging: (id: number) => del(`/production-summary/packaging/delete/${id}`),
  summary: (params?: QueryParams) =>
    get<Record<string, unknown>>('/production-summary/summary', { year: new Date().getFullYear(), ...params }),
}

// ===== 每日生产报表（重构版）=====
export const dailyProductionApi = {
  records: (params?: QueryParams) =>
    get('/daily-production/records', {
      year: new Date().getFullYear(),
      month: new Date().getMonth() + 1,
      ...params,
    }),
  createRecord: (data: Record<string, unknown>) => post('/daily-production/records', data),
  updateRecord: (id: number, data: Record<string, unknown>) => put(`/daily-production/records/${id}`, data),
  deleteRecord: (id: number) => del(`/daily-production/records/${id}`),
  dailySummary: (date: string) => get('/daily-production/daily-summary', { date }),
  monthlySummary: (params?: QueryParams) =>
    get('/daily-production/monthly-summary', {
      year: new Date().getFullYear(),
      month: new Date().getMonth() + 1,
      ...params,
    }),
  export: (params?: QueryParams) => download('/daily-production/export', 'production_report.xlsx', params),
  productInfo: (productId: number) => get<{ success: boolean; data: { id: number; name: string; barcode: string; price: number } }>(`/daily-production/product-info/${productId}`),
}

// ===== 报表 =====
export const reportApi = {
  orderLogs: (params?: QueryParams) => get<Record<string, unknown>[]>('/reports/order-logs', params),
  stockinLogs: (params?: QueryParams) => get<Record<string, unknown>[]>('/reports/stockin-logs', params),
  stockoutLogs: (params?: QueryParams) => get<Record<string, unknown>[]>('/reports/stockout-logs', params),
  deductionLogs: (params?: QueryParams) => get<Record<string, unknown>[]>('/reports/deduction-logs', params),
  customerNames: () => get<string[]>('/reports/customer-names'),
}

// ===== 用户/权限 =====
export const userApi = {
  list: (params?: QueryParams) => get<{ users: User[]; total: number }>('/users/list', params),
  create: (data: Partial<User>) => post<User>('/users/create', data),
  update: (id: number, data: Partial<User>) => put<User>(`/users/edit/${id}`, data),
  toggle: (id: number) => post(`/users/toggle/${id}`),
  delete: (id: number) => del(`/users/delete/${id}`),
  getPermission: (id: number) => get<{ permission_ids: number[] }>(`/users/permission/${id}`),
  savePermission: (id: number, permissionIds: number[]) =>
    post(`/users/permission/${id}`, { permission_ids: permissionIds }),
}

export const permissionApi = {
  list: () => get<PermissionItem[]>('/permissions/list'),
  tree: () => get<PermissionItem[]>('/permissions/tree'),
}

// ===== Dashboard =====
interface DashboardResponse<T = unknown> {
  success: boolean;
  data: T;
}

export const dashboardApi = {
  stats: async () => {
    const resp = await get<DashboardResponse<Record<string, unknown>>>('/dashboard/stats');
    return resp.data;
  },
  activities: () => get<Record<string, unknown>[]>('/dashboard/activities'),
  navSections: () => get<NavSection[] | Record<string, { name: string; items: Array<{ name: string; url: string; icon?: string; code: string; permission_codes: string[] }> }>>('/dashboard/nav-sections'),
}

// ===== OCR =====
export const ocrApi = {
  createTask: () => post<{ task_id: string }>('/ocr-import/create-task'),
  upload: (sessionId: string, formData: FormData) => upload('/ocr-import/upload', formData),
  progress: (taskId: string) => get<{ progress: number; status: string }>(`/ocr-import/progress/${taskId}`),
}

// ===== 出货计划 =====
export const planApi = {
  list: (params?: QueryParams) => get<Record<string, unknown>[]>('/plans/list', params),
  detail: (id: number) => get<Record<string, unknown>>(`/plans/detail/${id}`),
  create: (data: Record<string, unknown>) => post<Record<string, unknown>>('/plans/create', data),
  update: (id: number, data: Record<string, unknown>) => put<Record<string, unknown>>(`/plans/edit/${id}`, data),
  delete: (id: number) => del(`/plans/delete/${id}`),
  updateDetail: (detailId: number, data: Record<string, unknown>) => put(`/plans/details/${detailId}`, data),
  deleteDetail: (detailId: number) => del(`/plans/details/${detailId}`),
  addDetails: (planId: number, details: Record<string, unknown>[]) => post(`/plans/details/add?plan_id=${planId}`, { details }),
  monthly: (params?: QueryParams) => get<Record<string, unknown>>('/plans/monthly', params),
  customerSummary: (params?: QueryParams) => get<Record<string, unknown>>('/plans/customer-summary', params),
  inventoryCompare: (params?: QueryParams) => get<Record<string, unknown>>('/plans/inventory-compare', params),
  shipmentProgress: (planId: number) => get<ShipmentRecord[]>(`/plans/shipment/progress?plan_id=${planId}`),
  shipmentRecords: (planId: number) => get<ShipmentRecord[]>(`/plans/shipment/records?plan_id=${planId}`),
  upload: (formData: FormData) => upload('/plans/upload', formData),
  stagingList: () => get<StagingOrder[]>('/plans/staging/list'),
  stagingValidate: () => post<{ valid: boolean; errors?: string[] }>('/plans/staging/validate'),
  stagingConfirm: (data: Record<string, unknown>) => post('/plans/staging/confirm', data),
  stagingClear: () => del('/plans/staging/clear'),
  validateBarcode: (q: string) => get<{ valid: boolean }>('/plans/validate-barcode', { q }),
  downloadTemplate: () => download('/plans/template/download', '出货计划导入模板.xlsx'),
}

// ===== 辅助 =====
export const auxApi = {
  batchSubmitStockins: (data: Record<string, unknown>) => post('/aux/batch-submit-stockins', data),
  batchSubmitStockouts: (data: Record<string, unknown>) => post('/aux/batch-submit-stockouts', data),
  productSearch: (q: string) => get<Product[]>('/aux/product-search', { q }),
  availableShipment: (productId: number, customer: string) =>
    get<{ available: number }>('/aux/available-shipment', { product_id: productId, customer }),
  downloadTemplate: () => download('/batch/download-template', '统一导入模板.xlsx'),
}

// ===== 数据备份 =====
export const backupApi = {
  tables: () => get<ApiResponse<{ name: string; rows: number }[]>>('/backup/tables'),
  exportBackup: (remark: string, format: string = 'zip') =>
    download('/backup/export', `erp_backup_${new Date().toISOString().slice(0, 19).replace(/[:-]/g, '')}.${format === 'zip' ? 'zip' : 'json'}`, { remark, format }),
  validateFile: (formData: FormData) => upload<ApiResponse>('/backup/validate', formData),
  importBackup: (formData: FormData) => {
    return upload('/backup/import?confirm=true', formData)
  },
  saveToServer: (remark: string) => post<ApiResponse>(`/backup/save?remark=${encodeURIComponent(remark)}`),
  listServerBackups: () => get<ApiResponse<{ filename: string; size: number; created_at: string }[]>>('/backup/list'),
  restoreServerBackup: (filename: string) => post(`/backup/restore-by-name/${encodeURIComponent(filename)}?confirm=true`),
  deleteServerBackup: (filename: string) => del(`/backup/delete-by-name/${encodeURIComponent(filename)}`),
  saveIncremental: (remark: string, since?: string) =>
    post(`/backup/save-incremental?remark=${encodeURIComponent(remark)}${since ? '&since=' + encodeURIComponent(since) : ''}`),
  restoreIncremental: (filename: string) =>
    post(`/backup/restore-incremental/${encodeURIComponent(filename)}?confirm=true`),
  asyncImport: (formData: FormData) => upload<ApiResponse>('/backup/async-import?confirm=true', formData),
  asyncRestoreByName: (filename: string) => post<ApiResponse>(`/backup/async-restore-by-name/${encodeURIComponent(filename)}?confirm=true`),
  getProgress: (taskId: string) => get(`/backup/progress/${taskId}`),
  integrityCheck: () => post<ApiResponse>('/backup/integrity-check'),
  getRecords: (page: number = 1, pageSize: number = 20) =>
    get<ApiResponse>(`/backup/records?page=${page}&page_size=${pageSize}`),
  getSchedule: () => get<ApiResponse>('/backup/schedule'),
  triggerSchedule: (taskName: string) => post<ApiResponse>(`/backup/schedule/trigger?task_name=${encodeURIComponent(taskName)}`),
  getStatus: () => get<ApiResponse>('/backup/status'),
}

// ===== App版本管理 =====
export const appUpdateApi = {
  list: (platform: string = 'android') => get('/app/versions', { platform }),
  checkLatest: (currentVersionCode: number, platform: string = 'android') => get('/app/latest', { platform, current_version_code: currentVersionCode }),
  upload: (formData: FormData) => upload('/app/upload', formData),
  publish: (versionId: number) => post(`/app/${versionId}/publish`),
}

// ===== 订单批次号 =====
export const orderBatchApi = {
  orders: (params?: QueryParams) => get<{ success: boolean; data: OrderBatchItem[]; total: number }>('/order-batch/orders', params),
  updateBatchNo: (orderId: number, data: BatchNoUpdatePayload) => put<{ success: boolean; message: string; updated_count: number }>(`/order-batch/orders/${orderId}/batch-no`, data),
  batchAssign: (data: BatchAssignPayload) => post<{ success: boolean; message: string; updated_count: number }>('/order-batch/orders/batch-assign', data),
  completeBatch: (data: BatchCompletePayload) => post<{ success: boolean; message: string; completed_count: number; failed_orders: unknown[] }>('/order-batch/batch/complete', data),
  history: (params?: QueryParams) => get<{ success: boolean; data: OrderBatchItem[]; total: number }>('/order-batch/history', params),
  whitelist: () => get<{ customers: string[] }>('/order-batch/whitelist'),
}
