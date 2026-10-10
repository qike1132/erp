import { get } from './request'
import type { ApiResponse, QueryParams } from '@/types'

/** 产品搜索建议项（后端 `auxiliary.py::ProductSearchItem`，裸数组响应） */
export interface ProductSearchItem {
  id: number
  name: string
  barcode: string
  price?: number
  current_stock?: number
}

/** 可用备货单项（后端 `auxiliary.py::AvailableStockinItem`，裸数组响应） */
export interface AvailableStockinItem {
  id: number
  product_id: number
  product_name?: string
  quantity: number
  customer?: string
  stockin_date?: string
  available?: number
}

/**
 * 辅助数据查询 API
 * - productSearch: 产品搜索
 * - availableStockins: 可用备货量查询
 * - availableShipment: 库存可出货数量查询
 */
export const auxApi = {
  /**
   * 产品搜索。
   *
   * ⚠️ 后端 `response_model=list[ProductSearchItem]` 返回**裸数组**，不是 `{ products }`。
   * 原声明 `get<{ products?: unknown }>` 与实际响应不符（调用方若读 `res.products` 恒为 undefined）。
   * 空关键词时后端直接返回 `[]`。
   *
   * `opts.customer`：按客户过滤可见范围（后端口径：未挂客户的 SKU 对所有客户可见）。
   * 不传 = 不过滤，与改造前行为一致。下单/出货/备货/备货计划共用本端点。
   *
   * `q` 留空 + 带客户 = **浏览模式**（下单页点开 SKU 列表用），一次列一批；
   * 留空且不带客户时后端返回空数组 —— 见 fastapi_app/api/v1/endpoints/auxiliary.py。
   */
  productSearch: (q: string, opts?: { customer?: string; customerId?: number; limit?: number }) =>
    get<ProductSearchItem[]>('/aux/product-search', {
      q,
      customer: opts?.customer || undefined,
      customer_id: opts?.customerId,
      limit: opts?.limit,
    }),
  /**
   * 可用备货量查询（`GET /aux/available-stockins`，裸数组响应）。
   *
   * 产品与客户二者都需传入才能定位；调用方据此汇总可用量。
   */
  availableStockins: (params: { product_id: number; customer: string }) =>
    get<AvailableStockinItem[]>('/aux/available-stockins', params),
  availableShipment: (params: {
    product_id: number
    customer: string
  }) => get<ApiResponse<unknown>>('/aux/available-shipment', params),
}
