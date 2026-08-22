import { get } from './request'
import type { ApiResponse, QueryParams } from '@/types'

/**
 * 辅助数据查询 API
 * - productSearch: 产品搜索
 * - availableShipment: 库存可出货数量查询
 */
export const auxApi = {
  productSearch: (q: string) => get<{ products?: unknown }>('/aux/product-search', { q }),
  availableShipment: (params: {
    product_id: number
    customer: string
    order_type?: string
    country?: string
  }) => get<ApiResponse<unknown>>('/aux/available-shipment', params),
}