import { get } from './request'
import type { NavSection } from '@/types'

interface DashboardResponse<T = unknown> {
  success: boolean
  data: T
}

export interface MobileDeptData {
  name: string
  daily_output: number
  output_value: number
}

export interface MobileStockData {
  today_quantity: number
  today_amount: number
  month_quantity: number
  month_amount: number
  total_quantity: number
  total_amount: number
}

export interface MobileProductionData {
  total_value: number
  departments: MobileDeptData[]
}

export interface MobileShippingData {
  daily_qty: number
  total_amount: number
}

export interface MobileOrderData {
  daily_qty: number
  daily_amount: number
  total_amount: number
  total_qty: number
}

export interface MobileWarehouseData {
  in_qty: number
  in_amount: number
  out_qty: number
  out_amount: number
}

export interface MobileDashboardData {
  stock: MobileStockData
  production: MobileProductionData
  shipping: MobileShippingData
  orders: MobileOrderData
  warehouse: MobileWarehouseData
}

export const dashboardApi = {
  stats: async () => {
    const resp = await get<DashboardResponse<Record<string, unknown>>>('/dashboard/stats');
    return resp.data;
  },
  mobile: async (): Promise<MobileDashboardData> => {
    const resp = await get<DashboardResponse<MobileDashboardData>>('/dashboard/mobile');
    return resp.data;
  },
  activities: () => get<Record<string, unknown>[]>('/dashboard/activities'),
  navSections: () => get<NavSection[] | Record<string, { name: string; items: Array<{ name: string; url: string; icon?: string; code: string; permission_codes: string[] }> }>>('/dashboard/nav-sections'),
}
