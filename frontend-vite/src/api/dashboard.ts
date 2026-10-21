import { get } from './request'
import type { NavSection, WithItems, PickRequired } from '@/types'
import type { MobileDeptData as GenMobileDeptData, MobileShippingData as GenMobileShippingData, MobileStockData as GenMobileStockData, MobileWarehouseData as GenMobileWarehouseData, MobileProductionData as GenMobileProductionData, MobileOrderData as GenMobileOrderData } from '@/types/api'

interface ApiEnvelope<T = unknown> {
  success: boolean
  data: T
}

export type MobileDeptData = Required<GenMobileDeptData>

export type MobileStockData = Required<GenMobileStockData>

export type MobileProductionData = WithItems<GenMobileProductionData, 'departments', MobileDeptData>

export type MobileShippingData = Required<GenMobileShippingData>

export type MobileOrderData = PickRequired<GenMobileOrderData, 'daily_qty' | 'daily_amount' | 'total_amount' | 'total_qty'>

export type MobileWarehouseData = Required<GenMobileWarehouseData>

export interface MobileDashboardData {
  stock: MobileStockData
  production: MobileProductionData
  shipping: MobileShippingData
  orders: MobileOrderData
  warehouse: MobileWarehouseData
}

export const dashboardApi = {
  stats: async () => {
    const resp = await get<ApiEnvelope<Record<string, unknown>>>('/dashboard/stats');
    return resp.data;
  },
  mobile: async (): Promise<MobileDashboardData> => {
    const resp = await get<ApiEnvelope<MobileDashboardData>>('/dashboard/mobile');
    return resp.data;
  },
  activities: () => get<Record<string, unknown>[]>('/dashboard/activities'),
  navSections: () => get<NavSection[] | Record<string, { name: string; items: Array<{ name: string; url: string; icon?: string; code: string; permission_codes: string[] }> }>>('/dashboard/nav-sections'),
}
