import service, { get } from './request'
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
  // 导航数据是全局认证态，不是路由数据：不能走 get() 的路由级取消。
  // 否则登录后 init(true) 发起的请求会被随后的 router.push 取消（被 _silenceCanceled
  // 变成永不 settle），侧边栏将一直空白到整页刷新（2026-10-22 生产事故）。
  navSections: () => service.get('/dashboard/nav-sections') as Promise<NavSection[] | Record<string, { name: string; items: Array<{ name: string; url: string; icon?: string; code: string; permission_codes: string[] }> }>>,
}
