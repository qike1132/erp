import { get, post, put, del } from './request'
import type { Supplier, QueryParams } from '@/types'

export const supplierApi = {
  list: (params?: QueryParams) => get<{ suppliers: Supplier[]; total: number }>('/suppliers/list', params),
  /** 供应商下拉选项（id + 名称，实时，不缓存）——供 BOM 配置等选择器使用 */
  options: () => get<{ suppliers: { id: number; name: string }[] }>('/suppliers/options'),
  create: (data: Partial<Supplier>) => post<Supplier>('/suppliers/create', data),
  update: (id: number, data: Partial<Supplier>) => put<Supplier>(`/suppliers/edit/${id}`, data),
  delete: (id: number) => del(`/suppliers/delete/${id}`),
  toggleStatus: (id: number) => post(`/suppliers/toggle-status/${id}`),
}
