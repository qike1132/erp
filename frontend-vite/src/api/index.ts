import { get, post, put, del, upload, download } from './request'

// ===== 认证 =====
export const authApi = {
  login: (data: { username: string; password: string }) => post('/auth/login', data),
  logout: () => post('/auth/logout'),
  me: () => get<any>('/auth/me'),
}

// ===== 订单 =====
export const orderApi = {
  list: (params?: Record<string, any>) => get('/orders/list', params),
  detail: (id: number) => get(`/orders/${id}`),
  create: (data: any) => post('/orders/create', data),
  update: (id: number, data: any) => put(`/orders/edit/${id}`, data),
  delete: (id: number) => del(`/orders/delete/${id}`),
  lock: (id: number) => post(`/orders/lock/${id}`),
  unlock: (id: number) => post(`/orders/unlock/${id}`),
  deductStock: (id: number) => post(`/orders/deduct-stock/${id}`),
  staging: {
    add: (data: any) => post('/staging-orders/add', data),
    list: () => get('/staging-orders/list'),
    delete: (id: number) => del(`/staging-orders/${id}`),
    confirm: () => post('/staging-orders/confirm'),
  },
}

// ===== 产品 =====
export const productApi = {
  list: (params?: Record<string, any>) => get('/products/list', params),
  detail: (id: number) => get(`/products/${id}`),
  create: (data: any) => post('/products/create', data),
  update: (id: number, data: any) => put(`/products/edit/${id}`, data),
  delete: (id: number) => del(`/products/delete/${id}`),
  search: (q: string) => get('/products/search', { q }),
  bom: (productId: number, items: any[]) => post(`/products/bom/${productId}`, { items }),
  // BOM management (purchase-center API)
  loadBom: (productId: number) => get(`/purchase-center/product/${productId}/bom`),
  saveBom: (productId: number, bomData: any) => post(`/purchase-center/product/${productId}/bom`, bomData),
  searchProductsForBom: (keyword: string) => get('/purchase-center/products/search', { keyword }),
  bomPreview: (productId: number) => get(`/purchase-center/products/${productId}/bom-preview`),
  copyBom: (targetProductId: number, sourceProductId: number, overwrite: boolean) =>
    post(`/purchase-center/products/${targetProductId}/copy-bom`, { source_product_id: sourceProductId, overwrite }),
}

// ===== 客户 =====
export const customerApi = {
  list: (params?: Record<string, any>) => get('/customers/list', params),
  create: (data: any) => post('/customers/create', data),
  update: (id: number, data: any) => put(`/customers/edit/${id}`, data),
  toggleStatus: (id: number) => post(`/customers/toggle-status/${id}`),
  delete: (id: number) => del(`/customers/delete/${id}`),
  activeNames: () => get('/customers/active-names'),
}

// ===== 供应商 =====
export const supplierApi = {
  list: (params?: Record<string, any>) => get('/suppliers/list', params),
  create: (data: any) => post('/suppliers/create', data),
  update: (id: number, data: any) => put(`/suppliers/${id}`, data),
  delete: (id: number) => del(`/suppliers/delete/${id}`),
  toggleStatus: (id: number) => post(`/suppliers/${id}/toggle`),
  search: (q: string) => get('/suppliers/search', { q }),
  activeNames: () => get('/suppliers/active-names'),
}

// ===== 库存 =====
export const stockApi = {
  stockins: (params?: Record<string, any>) => get('/stock/in/list', params),
  stockouts: (params?: Record<string, any>) => get('/stock/out/list', params),
  inventory: (params?: Record<string, any>) => get('/stock/inventory', params),
  deleteStockin: (id: number) => del(`/stock/in/delete/${id}`),
  deleteStockout: (id: number) => del(`/stock/out/delete/${id}`),
  // Product search (autocomplete)
  searchProducts: (q: string) => get('/aux/product-search', { q }),
  // Available shipment check
  availableShipment: (productId: number, customer: string) =>
    get('/aux/available-shipment', { product_id: productId, customer }),
  // Staging stockins
  stagingStockins: {
    list: () => get('/staging-stockins'),
    add: (data: any) => post('/staging-stockins', data),
    delete: (id: number) => del(`/staging-stockins/${id}`),
    confirm: () => post('/staging-stockins/confirm'),
    clear: () => del('/staging-stockins/clear'),
    importExcel: (formData: FormData) => upload('/staging-stockins/import', formData),
  },
  // Staging stockouts
  stagingStockouts: {
    list: (sessionId?: string) => get('/staging-stockouts', sessionId ? { session_id: sessionId } : undefined),
    add: (data: any) => post('/staging-stockouts', data),
    delete: (id: number) => del(`/staging-stockouts/${id}`),
    confirm: (sessionId?: string) =>
      post('/staging-stockouts/confirm', sessionId ? { session_id: sessionId } : undefined),
    clear: (sessionId?: string) =>
      del(`/staging-stockouts/clear${sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ''}`),
    importExcel: (formData: FormData) => upload('/staging-stockouts/import', formData),
  },
  // Batch submit (direct, no staging)
  batchSubmitStockins: (stockins: any[]) => post('/aux/batch-submit-stockins', { stockins }),
  batchSubmitStockouts: (stockouts: any[]) => post('/aux/batch-submit-stockouts', { stockouts }),
  // Export
  exportInventory: (params?: Record<string, any>) => download('/stock/export-inventory', '库存汇总.xlsx', params),
  // Template download
  downloadTemplate: () => download('/batch/download-template', '统一导入模板.xlsx'),
}

// ===== 采购 =====
export const purchaseApi = {
  orders: (params?: Record<string, any>) => get('/purchase-center/orders', params),
  unprocessedOrders: () => get('/purchase-center/unprocessed-orders'),
  completeOrder: (id: number) => post(`/purchase-center/orders/complete`, { order_id: id }),
  batchComplete: (ids: number[]) => post('/purchase-center/orders/batch-complete', { ids }),
  deleteOrder: (id: number) => del(`/purchase-center/orders/${id}`),
  batchDelete: (ids: number[]) => post('/purchase-center/orders/batch-delete', { ids }),
  updateOrder: (id: number, data: any) => put(`/purchase-center/orders/${id}`, data),
  oneClickGenerate: (data: any) => post('/purchase-center/orders/one-click-generate', data),
  orderDetail: (id: number) => get(`/purchase-center/orders/${id}`),
  completed: (params?: Record<string, any>) => get('/purchase-center/orders/completed', params),
  exportCompleted: (params?: Record<string, any>) => post('/purchase-center/orders/completed/export', params),
  quickFilters: () => get('/purchase-center/orders/completed/quick-filters'),
  suggestions: (field: string, q: string) => get('/purchase-center/orders/completed/suggestions', { field, q }),
  factorySummary: (ids: number[]) => post('/purchase-center/orders/factory-summary', { ids }),
  supplierSummary: (ids: number[]) => post('/purchase-center/orders/supplier-summary', { ids }),
  saveFactoryEdits: (edits: any[]) => post('/purchase-center/orders/factory-summary/save', { edits }),
  supplierSummaryExport: (ids: number[]) => post('/purchase-center/orders/supplier-summary-export', { ids }),
  // Material calculator
  products: (params?: Record<string, any>) => get('/purchase-center/products', params),
  searchSuggestions: (q: string) => get('/purchase-center/products/search-suggestions', { q }),
  calculate: (orders: Array<{ product_id: number; quantity: number }>) =>
    post('/purchase-center/calculate', { orders }),
}

// ===== 审批 =====
export const approvalApi = {
  list: (params?: Record<string, any>) => get('/approvals/list', params),
  approve: (id: number) => post(`/approvals/approve/${id}`),
  reject: (id: number, reason: string) => post(`/approvals/reject/${id}`, { reason }),
}

// ===== 批次 =====
export const batchApi = {
  list: (params?: Record<string, any>) =>
    get('/production-summary/craft/list', { year: new Date().getFullYear(), ...params }),
  stats: () => get('/production-summary/summary'),
}

// ===== 物料 =====
export const materialApi = {
  overview: () => get('/material-registrations/stats/overview'),
  trend: (days: number) => get('/material-registrations/stats/trend', { days }),
  distribution: () => get('/material-registrations/stats/distribution'),
  registrations: (params?: Record<string, any>) => get('/material-registrations/registrations', params),
  registrationDetail: (id: number) => get(`/material-registrations/registrations/${id}`),
  history: (params?: Record<string, any>) => get('/material-registrations/history', params),
  receive: (id: number, data: any) => post(`/material-registrations/items/${id}/receive`, data),
  purchaseOrderPreview: (orderNo: string) =>
    get(`/material-registrations/purchase-orders/preview/${encodeURIComponent(orderNo)}`),
  export: (params?: Record<string, any>) => post('/material-registrations/export', params),
}

// ===== 生产 =====
export const productionApi = {
  craft: (params?: Record<string, any>) =>
    get('/production-summary/craft/list', {
      year: new Date().getFullYear(),
      month: new Date().getMonth() + 1,
      ...params,
    }),
  createCraft: (data: any) => post('/production-summary/craft/create', data),
  editCraft: (id: number, data: any) => put(`/production-summary/craft/edit/${id}`, data),
  deleteCraft: (id: number) => del(`/production-summary/craft/delete/${id}`),
  packaging: (params?: Record<string, any>) =>
    get('/production-summary/packaging/list', {
      year: new Date().getFullYear(),
      month: new Date().getMonth() + 1,
      ...params,
    }),
  createPackaging: (data: any) => post('/production-summary/packaging/create', data),
  editPackaging: (id: number, data: any) => put(`/production-summary/packaging/edit/${id}`, data),
  deletePackaging: (id: number) => del(`/production-summary/packaging/delete/${id}`),
  summary: (params?: Record<string, any>) =>
    get('/production-summary/summary', { year: new Date().getFullYear(), ...params }),
}

// ===== 报表 =====
export const reportApi = {
  orderLogs: (params?: Record<string, any>) => get('/reports/order-logs', params),
  stockinLogs: (params?: Record<string, any>) => get('/reports/stockin-logs', params),
  stockoutLogs: (params?: Record<string, any>) => get('/reports/stockout-logs', params),
  deductionLogs: (params?: Record<string, any>) => get('/reports/deduction-logs', params),
  customerNames: () => get('/reports/customer-names'),
}

// ===== 用户/权限 =====
export const userApi = {
  list: (params?: Record<string, any>) => get('/users/list', params),
  create: (data: any) => post('/users/create', data),
  update: (id: number, data: any) => put(`/users/edit/${id}`, data),
  toggle: (id: number) => post(`/users/toggle/${id}`),
  delete: (id: number) => del(`/users/delete/${id}`),
  getPermission: (id: number) => get(`/users/permission/${id}`),
  savePermission: (id: number, permissionIds: number[]) =>
    post(`/users/permission/${id}`, { permission_ids: permissionIds }),
}

export const permissionApi = {
  list: () => get('/permissions/list'),
  tree: () => get('/permissions/tree'),
}

// ===== Dashboard =====
export const dashboardApi = {
  stats: () => get('/dashboard/stats'),
  activities: () => get('/dashboard/activities'),
  navSections: () => get('/dashboard/nav-sections'),
}

// ===== OCR =====
export const ocrApi = {
  createTask: () => post('/ocr-import/create-task'),
  upload: (sessionId: string, formData: FormData) => upload('/ocr-import/upload', formData),
  progress: (taskId: string) => get(`/ocr-import/progress/${taskId}`),
}

// ===== 出货计划 =====
export const planApi = {
  list: (params?: Record<string, any>) => get('/plans/list', params),
  detail: (id: number) => get(`/plans/detail/${id}`),
  create: (data: any) => post('/plans/create', data),
  update: (id: number, data: any) => put(`/plans/edit/${id}`, data),
  delete: (id: number) => del(`/plans/delete/${id}`),
  updateDetail: (detailId: number, data: any) => put(`/plans/details/${detailId}`, data),
  deleteDetail: (detailId: number) => del(`/plans/details/${detailId}`),
  addDetails: (planId: number, details: any[]) => post(`/plans/details/add?plan_id=${planId}`, { details }),
  monthly: (params?: Record<string, any>) => get('/plans/monthly', params),
  customerSummary: (params?: Record<string, any>) => get('/plans/customer-summary', params),
  inventoryCompare: (params?: Record<string, any>) => get('/plans/inventory-compare', params),
  shipmentProgress: (planId: number) => get('/plans/shipment/progress', { plan_id: planId }),
  shipmentRecords: (planId: number) => get('/plans/shipment/records', { plan_id: planId }),
  upload: (formData: FormData) => upload('/plans/upload', formData),
  stagingList: () => get('/plans/staging/list'),
  stagingValidate: () => post('/plans/staging/validate'),
  stagingConfirm: (data: any) => post('/plans/staging/confirm', data),
  stagingClear: () => del('/plans/staging/clear'),
  validateBarcode: (q: string) => get('/plans/validate-barcode', { q }),
  downloadTemplate: () => download('/plans/template/download', '出货计划导入模板.xlsx'),
}

// ===== 辅助 =====
export const auxApi = {
  batchSubmitStockins: (data: any) => post('/aux/batch-submit-stockins', data),
  batchSubmitStockouts: (data: any) => post('/aux/batch-submit-stockouts', data),
  productSearch: (q: string) => get('/aux/product-search', { q }),
  availableShipment: (productId: number, customer: string) =>
    get('/aux/available-shipment', { product_id: productId, customer }),
  downloadTemplate: () => download('/batch/download-template', '统一导入模板.xlsx'),
}
