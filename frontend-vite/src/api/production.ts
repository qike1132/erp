import { get, post, put, del, download } from './request'
import type { ProductionCraft, QueryParams } from '@/types'

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
  summary: (params?: QueryParams) =>
    get<Record<string, unknown>>('/production-summary/summary', { year: new Date().getFullYear(), ...params }),
}

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
