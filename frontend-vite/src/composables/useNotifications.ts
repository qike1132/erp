/**
 * 通知中心 composable
 *
 * 封装未读数轮询、通知列表加载、单条/全部已读等逻辑，供桌面端 NotificationBell
 * 与移动端 MobileNotificationBell 共用。
 *
 * 轮询策略：组件 onMounted 启动 setInterval（默认 30s），onUnmounted 清理。
 * 多个组件同时挂载时各自轮询，去重由 request.ts 的 GET inflight 缓存兜底。
 */
import { ref, readonly } from 'vue'
import { notificationApi, type Notification } from '@/api/notification'

const POLL_INTERVAL_MS = 30_000

export function useNotifications() {
  const unreadCount = ref(0)
  const list = ref<Notification[]>([])
  const total = ref(0)
  const loading = ref(false)
  const marking = ref(false)

  let timer: number | null = null

  /** 拉取未读数（轮询入口，静默失败） */
  async function fetchUnreadCount() {
    try {
      const res = await notificationApi.unreadCount()
      unreadCount.value = Number(res?.count ?? 0)
    } catch (e) {
      // 静默失败，避免轮询报错刷屏；401 由 request 拦截器跳登录
      if (import.meta.env.DEV) console.warn('[notifications] unread-count failed', e)
    }
  }

  /** 拉取通知列表（默认仅未读，最多 20 条） */
  async function fetchList(onlyUnread = true) {
    loading.value = true
    try {
      const res = await notificationApi.list({ page: 1, page_size: 20, only_unread: onlyUnread })
      list.value = res?.data ?? []
      total.value = res?.total ?? 0
    } catch (e) {
      if (import.meta.env.DEV) console.warn('[notifications] list failed', e)
      list.value = []
      total.value = 0
    } finally {
      loading.value = false
    }
  }

  /** 标记单条已读，乐观更新本地列表（通过 id 在内部 ref 中查找原始对象） */
  async function markAsRead(id: number) {
    const notification = list.value.find((n) => n.id === id)
    if (!notification || notification.is_read) return
    // 乐观更新（操作内部非 readonly 的 ref）
    notification.is_read = true
    unreadCount.value = Math.max(0, unreadCount.value - 1)
    try {
      await notificationApi.markAsRead(id)
    } catch (e) {
      // 回滚
      notification.is_read = false
      unreadCount.value += 1
      if (import.meta.env.DEV) console.warn('[notifications] markAsRead failed', e)
      throw e
    }
  }

  /** 全部已读 */
  async function markAllAsRead() {
    if (marking.value || unreadCount.value === 0) return
    marking.value = true
    const prevCount = unreadCount.value
    try {
      await notificationApi.markAllAsRead()
      unreadCount.value = 0
      // 本地列表全部标记已读（操作内部非 readonly 的 ref）
      list.value.forEach((n) => { n.is_read = true })
    } catch (e) {
      unreadCount.value = prevCount
      if (import.meta.env.DEV) console.warn('[notifications] markAllAsRead failed', e)
      throw e
    } finally {
      marking.value = false
    }
  }

  /** 启动轮询：先立即拉取一次，再 setInterval */
  function startPolling() {
    stopPolling()
    fetchUnreadCount()
    timer = window.setInterval(fetchUnreadCount, POLL_INTERVAL_MS)
  }

  /** 停止并清理定时器，避免内存泄漏 */
  function stopPolling() {
    if (timer !== null) {
      window.clearInterval(timer)
      timer = null
    }
  }

  return {
    unreadCount: readonly(unreadCount),
    list: readonly(list),
    total: readonly(total),
    loading: readonly(loading),
    marking: readonly(marking),
    fetchUnreadCount,
    fetchList,
    markAsRead,
    markAllAsRead,
    startPolling,
    stopPolling,
  }
}
