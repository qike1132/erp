import { get, post, put, del } from './request'
import type { Product, QueryParams } from '@/types'

/** 产品写请求：除产品字段外可带客户归属（customer_ids 空数组 = 清空归属，回到所有客户可见） */
type ProductWritePayload = Partial<Product> & { customer_ids?: number[] }

export const productApi = {
  list: (params?: QueryParams) => get<{ items: Product[]; total: number }>('/products/list', params),
  detail: (id: number) => get<Product>(`/products/${id}`),
  create: (data: ProductWritePayload) => post<Product>('/products/create', data),
  update: (id: number, data: ProductWritePayload) => put<Product>(`/products/edit/${id}`, data),
  delete: (id: number) => del(`/products/delete/${id}`),
  search: (q: string) => get<Product[]>('/products/search', { q }),
  bom: (productId: number, items: Record<string, unknown>[]) => post(`/products/bom/${productId}`, { items }),
}
