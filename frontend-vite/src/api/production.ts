import { get, post, put, del, download } from './request'
import type {
  DailySummary,
  MonthlySummary,
  ProductionCraft,
  ProductionRecordListResponse,
  QueryParams,
  RecordsQuery,
  TrendResponse,
} from '@/types'

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
  /**
   * 明细列表。参数由调用方决定：传 year/month 或传 start_date/end_date（区间优先）。
   * 本层**不补默认值** —— 补了会让"区间"筛选被悄悄带上 year/month。
   */
  records: (params: RecordsQuery) =>
    get<ProductionRecordListResponse>('/daily-production/records', { ...params }),
  createRecord: (data: Record<string, unknown>) => post('/daily-production/records', data),
  updateRecord: (id: number, data: Record<string, unknown>) => put(`/daily-production/records/${id}`, data),
  deleteRecord: (id: number) => del(`/daily-production/records/${id}`),
  dailySummary: (date: string) => get<DailySummary>('/daily-production/daily-summary', { date }),
  monthlySummary: (params?: QueryParams) =>
    get<MonthlySummary>('/daily-production/monthly-summary', {
      year: new Date().getFullYear(),
      month: new Date().getMonth() + 1,
      ...params,
    }),
  /** 近 N 日按部门数量趋势（可跨月，后端上限 92 天） */
  trend: (params: { start_date: string; end_date: string; department?: string }) =>
    get<TrendResponse>('/daily-production/trend', params),
  export: (params?: QueryParams) => download('/daily-production/export', 'production_report.xlsx', params),
  productInfo: (productId: number) =>
    get<{ success: boolean; data: { id: number; name: string; barcode: string; price: number } }>(
      `/daily-production/product-info/${productId}`,
    ),
}
