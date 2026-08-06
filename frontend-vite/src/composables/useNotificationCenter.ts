/**
 * 通知中心专用 composable
 *
 * 封装全屏通知页所需的：分页列表、多选批量操作、单条/全部已读等功能。
 * 与 useNotifications 分离以保持未读数轮询的轻量。
 */
import { ref, readonly, computed } from 'vue'
import { notificationApi, type Notification, type NotificationListParams } from '@/api/notification'

const DEFAULT_PAGE_SIZE = 20

export function useNotificationCenter() {
  // 数据状态
  const list = ref<Notification[]>([])
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(DEFAULT_PAGE_SIZE)
  const loading = ref(false)
  const marking = ref(false)

  // 多选状态
  const selectedIds = ref<Set<number>>(new Set())
  const selectAll = computed({
    get: () => list.value.length > 0 && selectedIds.value.size === list.value.length,
    set: (val: boolean) => {
      if (val) {
        selectedIds.value = new Set(list.value.map((n) => n.id))
      } else {
        selectedIds.value = new Set()
      }
    },
  })
  const isIndeterminate = computed(
    () => selectedIds.value.size > 0 && selectedIds.value.size < list.value.length,
  )

  /** 拉取通知列表（仅返回当前用户的未读通知） */
  async function fetchList(resetPage = true) {
    if (resetPage) {
      page.value = 1
    }
    loading.value = true
    try {
      const params: NotificationListParams = {
        page: page.value,
        page_size: pageSize.value,
        only_unread: true,
      }

      const res = await notificationApi.list(params)
      list.value = res?.data ?? []
      total.value = res?.total ?? 0
      // 清除已选（分页切换后重置）
      selectedIds.value = new Set()
    } catch (e) {
      if (import.meta.env.DEV) console.warn('[notification-center] list failed', e)
      list.value = []
      total.value = 0
    } finally {
      loading.value = false
    }
  }

  /** 翻页 */
  function goToPage(p: number) {
    if (p < 1 || p > totalPages.value) return
    page.value = p
    fetchList(false)
  }

  /** 切换单条选中 */
  function toggleSelect(id: number) {
    const newSet = new Set(selectedIds.value)
    if (newSet.has(id)) {
      newSet.delete(id)
    } else {
      newSet.add(id)
    }
    selectedIds.value = newSet
  }

  /** 标记单条已读 */
  async function markAsRead(id: number) {
    const notification = list.value.find((n) => n.id === id)
    if (!notification || notification.is_read) return
    notification.is_read = true
    try {
      await notificationApi.markAsRead(id)
    } catch (e) {
      notification.is_read = false
      throw e
    }
  }

  /**
   * 确认已读：标记已读并立即从当前列表移除
   * 用于"确认已读"按钮的强交互场景
   */
  async function dismissFromList(id: number) {
    const notification = list.value.find((n) => n.id === id)
    const wasRead = notification?.is_read
    if (notification && !notification.is_read) {
      notification.is_read = true
    }
    // 先从本地列表移除（即时反馈），再请求后端
    list.value = list.value.filter((n) => n.id !== id)
    total.value = Math.max(0, total.value - 1)
    try {
      if (!wasRead) {
        await notificationApi.markAsRead(id)
      }
    } catch (e) {
      // 后端失败时回滚：恢复列表与已读状态
      if (notification) {
        list.value = [...list.value, notification]
        total.value += 1
        notification.is_read = false
      }
      throw e
    }
  }

  /** 批量标记已读（页面仅展示未读，标记后立即从列表移除） */
  async function markBatchAsRead(ids: number[]) {
    if (ids.length === 0 || marking.value) return
    marking.value = true
    // 乐观更新：记录受影响项并先从列表移除
    const affected = list.value.filter((n) => ids.includes(n.id) && !n.is_read)
    affected.forEach((n) => { n.is_read = true })
    list.value = list.value.filter((n) => !ids.includes(n.id) || n.is_read)
    total.value = Math.max(0, total.value - affected.length)
    try {
      await notificationApi.markBatchAsRead(ids)
      selectedIds.value = new Set()
    } catch (e) {
      // 回滚：恢复列表与已读状态
      list.value = [...list.value, ...affected]
      total.value += affected.length
      affected.forEach((n) => { n.is_read = false })
      throw e
    } finally {
      marking.value = false
    }
  }

  /** 全部标记已读 */
  async function markAllAsRead() {
    if (marking.value) return
    marking.value = true
    const unreadItems = list.value.filter((n) => !n.is_read)
    unreadItems.forEach((n) => { n.is_read = true })
    try {
      await notificationApi.markAllAsRead()
    } catch (e) {
      unreadItems.forEach((n) => { n.is_read = false })
      throw e
    } finally {
      marking.value = false
    }
  }

  const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))

  const hasSelection = computed(() => selectedIds.value.size > 0)
  const selectedCount = computed(() => selectedIds.value.size)

  const unreadIds = computed(() =>
    list.value.filter((n) => !n.is_read).map((n) => n.id),
  )

  return {
    // 数据
    list: readonly(list),
    total: readonly(total),
    page: readonly(page),
    pageSize: readonly(pageSize),
    totalPages: readonly(totalPages),
    loading: readonly(loading),
    marking: readonly(marking),
    // 多选
    selectedIds: readonly(selectedIds),
    selectAll,
    isIndeterminate: readonly(isIndeterminate),
    selectedCount: readonly(selectedCount),
    hasSelection: readonly(hasSelection),
    unreadIds: readonly(unreadIds),
    // 操作
    fetchList,
    goToPage,
    toggleSelect,
    markAsRead,
    dismissFromList,
    markBatchAsRead,
    markAllAsRead,
  }
}
