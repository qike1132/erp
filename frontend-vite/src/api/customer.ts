import { get, post, put, del } from './request'
import type { Customer, QueryParams } from '@/types'

export const customerApi = {
  list: (params?: QueryParams) => get<{ customers: Customer[]; total: number }>('/customers/list', params),
  create: (data: Partial<Customer>) => post<Customer>('/customers/create', data),
  update: (id: number, data: Partial<Customer>) => put<Customer>(`/customers/edit/${id}`, data),
  toggleStatus: (id: number) => post(`/customers/toggle-status/${id}`),
  delete: (id: number) => del(`/customers/delete/${id}`),
  activeNames: () => get<{ id: number; name: string }[]>('/customers/active-names'),
}
