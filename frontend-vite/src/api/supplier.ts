import { get, post, put, del } from './request'
import type { Supplier, QueryParams } from '@/types'

export const supplierApi = {
  list: (params?: QueryParams) => get<{ suppliers: Supplier[]; total: number }>('/suppliers/list', params),
  create: (data: Partial<Supplier>) => post<Supplier>('/suppliers/create', data),
  update: (id: number, data: Partial<Supplier>) => put<Supplier>(`/suppliers/edit/${id}`, data),
  delete: (id: number) => del(`/suppliers/delete/${id}`),
  toggleStatus: (id: number) => post(`/suppliers/toggle-status/${id}`),
}
