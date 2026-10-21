import { get, post, put, del, postDownload } from './request'
import type { MaterialCalcRow as GenMaterialCalcRow, SearchSuggestionResponse as GenSearchSuggestionResponse } from '@/types/api'
import type {
  Product, PurchaseOrder, UnprocessedOrder, QueryParams, ExportResponse,
  WithItems, WithRequired,
} from '@/types'

// === 物料计算器相关类型（与后端 schemas/purchase_center.py 对齐）===
export interface MaterialCalcProduct {
  id: number
  name: string
  barcode?: string | null
  has_bom: boolean
}

export type MaterialCalcRow = WithRequired<GenMaterialCalcRow, 'supplier_name' | 'material_name' | 'total_quantity' | 'unit'> // name 与 material_name 同值，保留以兼容两种口径

/**
 * 供应商导出数量行（对应后端 `SupplierExportQuantityItem`）。
 *
 * 与页面「供应商采购订单」各展示行一一对应：同一
 * (供应商, 物料, 规格, 单位) 在导出分组中命中时，用 `quantity` 覆盖该行数量。
 */
export interface SupplierExportQuantity {
  supplier_name: string
  material_name: string
  specification: string
  unit: string
  quantity: number
}

/**
 * 按「产品 × 作用域(角色)」分块的物料计算结果（对应后端
 * `schemas/purchase_center.py:MaterialCalcScopeGroup`）。
 *
 * `role_id === null` 表示产品级**默认 BOM**，后端保证**恒为首块**；块顺序由后端定死，
 * 前端不得重排（架构 §7#2）。`quantity` 为该产品订单总数量，各作用域共用、**不分摊**。
 * 每个分类的行内 `total_quantity` **已是结果**，前端不要再乘/除。
 */
export interface MaterialCalcScopeGroup {
  product_id: number
  product_name: string
  role_id: number | null
  role_name: string
  quantity: number
  filling: MaterialCalcRow[]
  fabric: MaterialCalcRow[]
  accessory: MaterialCalcRow[]
  packaging: MaterialCalcRow[]
}

export interface MaterialCalcResult {
  success: boolean
  // 扁平字段：全作用域合并口径（旧口径，保留不变）
  filling: MaterialCalcRow[]
  fabric: MaterialCalcRow[]
  accessory: MaterialCalcRow[]
  packaging: MaterialCalcRow[]
  // 追加：按「产品 × 作用域(角色)」分块（旧后端可能缺失 → 前端回退扁平渲染, A-5）
  groups?: MaterialCalcScopeGroup[] | null
  total_categories?: Record<string, number> | null
  message?: string | null
}

export interface MaterialOrderInput {
  product_id: number
  quantity: number
}

export interface ProductListResponse {
  success: boolean
  products: MaterialCalcProduct[]
  total: number
  pages: number
  current_page: number
}

export type SearchSuggestionResponse = WithItems<Required<GenSearchSuggestionResponse>, 'suggestions', MaterialCalcProduct>

// BOM 相关接口（从 productApi 迁移，属于采购中心域）
export const bomApi = {
  loadBom: (productId: number) => get<Record<string, unknown>>(`/purchase-center/product/${productId}/bom`),
  saveBom: (productId: number, bomData: Record<string, unknown>) => post(`/purchase-center/product/${productId}/bom`, bomData),
  searchProductsForBom: (keyword: string) => get<Product[]>('/purchase-center/products/search', { keyword }),
  bomPreview: (productId: number) => get<Record<string, unknown>>(`/purchase-center/products/${productId}/bom-preview`),
  /**
   * 复制 BOM。
   * @param targetProductId 目标产品 ID
   * @param sourceProductId 源产品 ID
   * @param overwrite 是否覆盖；角色模式下仅作用于目标角色（后端已收敛作用域）
   * @param roleId 目标角色 ID；传入时物料归属到该角色，为空/省略时按源产品结构复制
   * @param roleName 目标角色名称；仅在 roleId 为空时生效，后端按名称查找或新建角色
   */
  copyBom: (targetProductId: number, sourceProductId: number, overwrite: boolean, roleId?: number | null, roleName?: string | null) =>
    post(`/purchase-center/products/${targetProductId}/copy-bom`, {
      source_product_id: sourceProductId,
      overwrite,
      ...(roleId != null ? { role_id: roleId } : {}),
      ...(roleId == null && roleName ? { role_name: roleName } : {}),
    }),
}

/**
 * 记录查询导出明细行（对应后端 `export_completed_orders` 返回的 rows 元素）。
 *
 * 后端按「订单 × 采购明细」展开，故同一订单可能对应多行。
 */
export interface CompletedOrderExportRow {
  order_no: string
  completed_at?: string
  customer_name?: string | null
  supplier_name?: string | null
  material_name?: string | null
  material_code?: string
  specification?: string
  unit?: string
  quantity?: number
  unit_price?: number
  amount?: number
}

/** 记录查询导出响应体：后端返回明细行，由前端拼成 .xls */
export interface CompletedOrderExportResponse {
  success: boolean
  rows?: CompletedOrderExportRow[]
  message?: string
}

export const purchaseApi = {
  orders: (params?: QueryParams) => get<{ orders: PurchaseOrder[]; total: number; pages: number; current_page: number }>('/purchase-center/orders', params),
  unprocessedOrders: (params?: { page?: number; per_page?: number }) => get<{ orders: UnprocessedOrder[]; total: number; pages: number; current_page: number }>('/purchase-center/unprocessed-orders', params),
  /**
   * 下单完成。
   * @param spareRate 损耗率（千分之几）；省略时不进请求体 → 后端保留该采购单已存值
   */
  completeOrder: (id: number, spareRate?: number) =>
    post('/purchase-center/orders/complete',
      spareRate === undefined ? { order_id: id } : { order_id: id, spare_rate: spareRate }),
  /**
   * 批量下单完成。
   * @param spareRate 损耗率（千分之几）；省略时不进请求体 → 后端保留各单已存值
   */
  batchComplete: (ids: number[], spareRate?: number) =>
    post('/purchase-center/orders/batch-complete',
      spareRate === undefined ? { ids } : { ids, spare_rate: spareRate }),
  deleteOrder: (id: number) => del(`/purchase-center/orders/${id}`),
  batchDelete: (ids: number[]) => post('/purchase-center/orders/batch-delete', { ids }),
  updateOrder: (id: number, data: Partial<PurchaseOrder>) => put(`/purchase-center/orders/${id}`, data),
  /**
   * 补录采购明细单价（按明细 id）。
   * 一键生成路径没有价格来源（BOM 行无价字段），单价恒 0；这是唯一的补录入口。
   * 只改单价：不动数量/物料，也不删行。
   */
  updateItemPrices: (id: number, itemPrices: { id: number; unit_price: number }[]) =>
    put(`/purchase-center/orders/${id}`, { item_prices: itemPrices }),
  oneClickGenerate: (data: { composite_ids: string[] }) => post<{ success: boolean; message?: string; created_count?: number; orders?: { id: number; order_no: string }[]; idempotent?: boolean }>('/purchase-center/orders/one-click-generate', data),
  orderDetail: (id: number) => get<{ success: boolean; order?: PurchaseOrder; message?: string }>(`/purchase-center/orders/${id}`),
  completed: (params?: QueryParams) => get<{ orders: PurchaseOrder[]; total: number; pages: number; total_pages?: number }>('/purchase-center/orders/completed', params),
  exportCompleted: (params?: QueryParams) => post<CompletedOrderExportResponse>('/purchase-center/orders/completed/export', params),
  // 后端返回的是三个时段的计数（dict[str, int]），不是可配置的区间定义数组
  quickFilters: () => get<{ success?: boolean; quick_filters?: Record<string, number> }>('/purchase-center/orders/completed/quick-filters'),
  suggestions: (field: string, q: string) => get<string[]>('/purchase-center/orders/completed/suggestions', { field, q }),
  factorySummary: (ids: number[]) => post<Record<string, unknown>>('/purchase-center/orders/factory-summary', { ids }),
  supplierSummary: (ids: number[]) => post<Record<string, unknown>[]>('/purchase-center/orders/supplier-summary', { ids }),
  /**
   * 保存工厂汇总编辑。
   * - `edits` 可为空（用户仅交互了损耗率、无布料改动）；
   * - `spareRate` 省略时不进请求体 → 后端保留已存率（避免用 0 覆盖）；
   * - `orderIds` 为本次汇总涉及的采购单 ID，用于无编辑项时定位写入备品的目标。
   */
  saveFactoryEdits: (edits: Record<string, unknown>[], spareRate?: number, orderIds?: number[]) =>
    post('/purchase-center/orders/factory-summary/save', {
      edits,
      ...(spareRate !== undefined ? { spare_rate: spareRate } : {}),
      ...(orderIds && orderIds.length > 0 ? { order_ids: orderIds } : {}),
    }),
  summaryPrint: (ids: number[], format: string) => post<ExportResponse>('/purchase-center/orders/summary-print', { ids, format }),
  /**
   * 导出供应商采购订单汇总 Excel。
   * `quantities` 携带页面「供应商采购订单」各行的展示数量（含损耗率加放），
   * 后端据此覆盖导出数量，保证导出 Excel 与页面逐行一致；
   * 缺省时后端回退为明细原始数量口径（向后兼容）。
   */
  supplierSummaryExport: (ids: number[], supplierCount: number, quantities: SupplierExportQuantity[] = []) =>
    postDownload(
      '/purchase-center/orders/supplier-summary-export',
      quantities.length > 0 ? { ids, supplier_quantities: quantities } : { ids },
      supplierCount > 1 ? '供应商采购订单汇总.zip' : '供应商采购订单汇总.xlsx',
    ),
  products: (params?: QueryParams) => get<ProductListResponse>('/purchase-center/products', params),
  searchSuggestions: (q: string) => get<SearchSuggestionResponse>('/purchase-center/products/search-suggestions', { q }),
  calculate: (orders: MaterialOrderInput[]) =>
    post<MaterialCalcResult>('/purchase-center/calculate', { orders }),
}
