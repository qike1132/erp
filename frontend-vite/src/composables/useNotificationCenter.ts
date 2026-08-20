/**
 * 通知中心专用 composable
 *
 * 封装全屏通知页所需的：分页列表、多选批量操作、单条/全部已读等功能。
 * 与 useNotifications 分离以保持未读数轮询的轻量。
 */
import { ref, readonly, computed } from 'vue'
import { notificationApi, type Notification, type NotificationListParams } from '@/api/notification'
import {
  clearNotificationMemoryCache,
  fetchNotificationList,
  getNotificationMemorySnapshot,
} from './notificationMemoryCache'

const DEFAULT_PAGE_SIZE = 20

export function useNotificationCenter() {
  // 数据状态
  const list = ref<Notification[]>([])
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(DEFAULT_PAGE_SIZE)
  const loading = ref(false)
  const marking = ref(false)
  let loadRequestId = 0

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

  function applyListResponse(
    response: { data?: Notification[]; total?: number },
    resetSelection: boolean,
  ) {
    list.value = response.data ?? []
    total.value = response.total ?? 0
    if (resetSelection) {
      selectedIds.value = new Set()
    } else {
      // 后台刷新不打断用户当前选择，只保留仍存在于新列表的 id
      const visibleIds = new Set(list.value.map((notification) => notification.id))
      selectedIds.value = new Set(
        [...selectedIds.value].filter((id) => visibleIds.has(id)),
      )
    }
  }

  /** 实际请求；silent=true 时失败不清空当前已渲染的旧列表 */
  async function loadListFromApi(
    params: NotificationListParams,
    silent: boolean,
    requestId: number,
  ) {
    try {
      const response = await fetchNotificationList(params)
      // 翻页或重新加载后，旧响应不能覆盖当前页面。
      if (requestId !== loadRequestId) return
      applyListResponse(response, !silent)
    } catch (e) {
      if (import.meta.env.DEV) console.warn('[notification-center] list failed', e)
      if (requestId !== loadRequestId || silent) return
      list.value = []
      total.value = 0
    }
  }

  /**
   * 拉取通知列表（仅返回当前用户的未读通知）。
   *
   * 注意：通知列表只使用 5 秒的 JS 内存 SWR，不写入 sessionStorage；
   * 未读数仍由 useNotifications 每次挂载/每 30 秒实时请求。
   * force=true 用于「全部已读」等必须立即向服务端确认的场景。
   */
  async function fetchList(resetPage = true, force = false) {
    if (resetPage) {
      page.value = 1
    }
    const params: NotificationListParams = {
      page: page.value,
      page_size: pageSize.value,
      only_unread: true,
    }
    const requestId = ++loadRequestId

    if (!force) {
      const snapshot = getNotificationMemorySnapshot(params)
      if (snapshot) {
        // 先显示内存快照，避免快速返回通知页时出现 loading。
        applyListResponse(snapshot.response, true)
        loading.value = false
        // 新鲜快照不再重复请求；过期快照才后台静默校验。
        if (!snapshot.fresh) {
          void loadListFromApi(params, true, requestId)
        }
        return
      }
    }

    loading.value = true
    try {
      await loadListFromApi(params, false, requestId)
    } finally {
      if (requestId === loadRequestId) loading.value = false
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
    loadRequestId += 1
    clearNotificationMemoryCache()
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
    loadRequestId += 1
    clearNotificationMemoryCache()
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
    loadRequestId += 1
    clearNotificationMemoryCache()
    marking.value = true
    // 乐观更新：记录受影响项并先从列表移除
    const affected = list.value.filter((n) => ids.includes(n.id) && !n.is_read)
    const affectedIds = new Set(affected.map((n) => n.id))
    affected.forEach((n) => { n.is_read = true })
    // 只移除实际受影响的未读项；不能在设置 is_read=true 后再用状态判断，
    // 否则刚标记的项目会被错误地保留在列表中。
    list.value = list.value.filter((n) => !affectedIds.has(n.id))
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
    loadRequestId += 1
    clearNotificationMemoryCache()
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
