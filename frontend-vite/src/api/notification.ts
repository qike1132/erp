import { get, post } from './request'

/** 通知类型字面量（与后端 to_dict 对齐） */
export interface Notification {
  id: number
  user_id: number
  type: string
  title: string
  content: string | null
  related_order_id: number | null
  is_read: boolean
  created_at: string | null
}

/** 通知列表响应（对应 GET /notifications 返回结构） */
export interface NotificationListResponse {
  total: number
  page: number
  page_size: number
  data: Notification[]
}

/** 列表查询参数 */
export interface NotificationListParams {
  page?: number
  page_size?: number
  only_unread?: boolean
  [key: string]: unknown
}

/** 通知类型映射（前端维护，后端 type 字段对应用户可读名称） */
export const NOTIFICATION_TYPE_MAP: Record<string, string> = {
  new_order: '新订单',
  order_updated: '订单更新',
}

/** 所有通知类型选项（用于筛选下拉） */
export const NOTIFICATION_TYPE_OPTIONS = Object.entries(NOTIFICATION_TYPE_MAP).map(([value, label]) => ({
  value,
  label,
}))

/** 根据 type 获取可读名称 */
export function getNotificationTypeLabel(type: string): string {
  return NOTIFICATION_TYPE_MAP[type] || type
}

export const notificationApi = {
  unreadCount: () => get<{ count: number }>('/notifications/unread-count'),
  list: (params?: NotificationListParams) => get<NotificationListResponse>('/notifications', params),
  markAsRead: (id: number) => post<{ success: boolean; message: string }>(`/notifications/${id}/read`),
  /** 批量标记已读（逐条调用，带并发控制） */
  markBatchAsRead: async (ids: number[]): Promise<{ success: boolean; marked_count: number }> => {
    let markedCount = 0
    const CONCURRENCY = 5
    for (let i = 0; i < ids.length; i += CONCURRENCY) {
      const batch = ids.slice(i, i + CONCURRENCY)
      const results = await Promise.allSettled(
        batch.map((id) =>
          post<{ success: boolean; message: string }>(`/notifications/${id}/read`)
        )
      )
      markedCount += results.filter((r) => r.status === 'fulfilled' && r.value?.success).length
    }
    return { success: markedCount > 0, marked_count: markedCount }
  },
  markAllAsRead: () => post<{ success: boolean; marked_count: number }>('/notifications/read-all'),
}
