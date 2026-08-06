import { get, post, put, del } from './request'
import type { Product, QueryParams } from '@/types'

export const productApi = {
  list: (params?: QueryParams) => get<{ items: Product[]; total: number }>('/products/list', params),
  detail: (id: number) => get<Product>(`/products/${id}`),
  create: (data: Partial<Product>) => post<Product>('/products/create', data),
  update: (id: number, data: Partial<Product>) => put<Product>(`/products/edit/${id}`, data),
  delete: (id: number) => del(`/products/delete/${id}`),
  search: (q: string) => get<Product[]>('/products/search', { q }),
  bom: (productId: number, items: Record<string, unknown>[]) => post(`/products/bom/${productId}`, { items }),
}
