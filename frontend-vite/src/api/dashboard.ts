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
    // 该请求由 Vue Query 缓存持有（useDashboardStats），生命周期属于查询而不是路由：
    // 走 get() 的路由级取消时，登录后紧接着的 router.push 会把它 abort，
    // _silenceCanceled 再把取消变成永不 settle 的 Promise → 查询永久停在
    // fetchStatus='fetching'，组件挂载不会重新取数（首次登录仪表盘无数据、刷新才恢复）。
    const resp = await service.get<unknown, ApiEnvelope<Record<string, unknown>>>('/dashboard/stats');
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
