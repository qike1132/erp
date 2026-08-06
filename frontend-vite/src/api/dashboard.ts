import { get } from './request'
import type { NavSection } from '@/types'

interface DashboardResponse<T = unknown> {
  success: boolean
  data: T
}

export const dashboardApi = {
  stats: async () => {
    const resp = await get<DashboardResponse<Record<string, unknown>>>('/dashboard/stats');
    return resp.data;
  },
  activities: () => get<Record<string, unknown>[]>('/dashboard/activities'),
  navSections: () => get<NavSection[] | Record<string, { name: string; items: Array<{ name: string; url: string; icon?: string; code: string; permission_codes: string[] }> }>>('/dashboard/nav-sections'),
}
