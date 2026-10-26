/**
 * useNotificationCenterPage.ts — 通知中心页面逻辑
 *
 * 从 NotificationCenterView.vue 下沉的逻辑：
 * 组合 useNotificationCenter（分页列表/多选/已读）与 useNotifications（未读数轮询），
 * 附带结构化内容解析、订单跳转、批量/全部已读操作与页面生命周期。
 */
import { computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useNotificationCenter } from '@/composables/useNotificationCenter'
import { useNotifications } from '@/composables/useNotifications'
import { type Notification } from '@/api/notification'
import { useToast } from '@/composables/useToast'

// ==== 结构化内容类型 ====
export interface NotificationContentV2 {
  format_version: 2
  order_type: string
  order_no?: string
  customer?: string
  factory?: string
  products: Array<{ name: string; quantity: number | string }>
}

export type ParsedNotification = Notification & {
  _parsed?: NotificationContentV2 | null
}

/** 解析 v2 结构化通知内容（JSON），非 v2 或解析失败返回 null */
function parseContentV2(content: string | null | undefined): NotificationContentV2 | null {
  if (!content || typeof content !== 'string' || !content.startsWith('{')) return null
  try {
    const obj = JSON.parse(content)
    if (obj && obj.format_version === 2 && Array.isArray(obj.products)) {
      return obj as NotificationContentV2
    }
    return null
  } catch {
    return null
  }
}

/** 通知中心页面：列表 + 多选 + 已读 + 轮询 + 跳转 */
export function useNotificationCenterPage() {
  const router = useRouter()
  const { toast } = useToast()

  const {
    list,
    total,
    page,
    totalPages,
    loading,
    marking,
    selectedIds,
    selectAll,
    isIndeterminate,
    selectedCount,
    hasSelection,
    fetchList,
    goToPage,
    toggleSelect,
    dismissFromList,
    markBatchAsRead,
    markAllAsRead,
  } = useNotificationCenter()

  // 获取未读数（复用轮询 composable）
  const { unreadCount, fetchUnreadCount, startPolling, stopPolling } = useNotifications()

  // 处理后的列表（附带解析后的结构化内容）
  const processedList = computed<ParsedNotification[]>(() =>
    list.value.map((it) => ({ ...(it as ParsedNotification), _parsed: parseContentV2(it.content) })),
  )

  // 导航
  function goBack() {
    if (window.history.length > 1) {
      router.back()
    } else {
      router.push('/dashboard')
    }
  }

  function navigateToOrder(orderId: number) {
    router.push({ path: '/beile-order', query: { order_id: String(orderId) } })
  }

  // 通知项点击：跳转订单页 + 标记已读并从列表移除
  async function handleItemClick(item: Notification) {
    if (item.related_order_id) {
      navigateToOrder(item.related_order_id)
    }
    try {
      await dismissFromList(item.id)
      fetchUnreadCount()
    } catch {
      // 标记已读失败不阻塞跳转
    }
  }

  // 批量标记已读
  async function handleBatchMarkRead() {
    const ids = Array.from(selectedIds.value).filter(
      (id) => !list.value.find((n) => n.id === id)?.is_read,
    )
    if (ids.length === 0) {
      toast.info('所选通知均已读')
      return
    }
    try {
      await markBatchAsRead(ids)
      // 即时刷新未读数，保持头部徽章同步
      fetchUnreadCount()
      toast.success(`已标记 ${ids.length} 条为已读`)
    } catch (e) {
      // M8：部分失败时 composable 会回滚失败项并抛出带计数的错误——
      // 如实透出（「已标记 X 条，Y 条失败」），不要笼统说「操作失败」。
      const msg = e instanceof Error && e.message ? e.message : '批量操作失败，请重试'
      toast.error(msg)
    }
  }

  // 全部已读
  async function handleMarkAll() {
    try {
      await markAllAsRead()
      fetchUnreadCount()
      toast.success('已全部标记为已读')
      await fetchList(true, true)
    } catch {
      toast.error('操作失败，请重试')
    }
  }

  function clearSelection() {
    selectAll.value = false
  }

  // 生命周期
  onMounted(async () => {
    startPolling()
    await fetchList(true)
  })

  onUnmounted(() => {
    stopPolling()
  })

  return {
    list,
    total,
    page,
    totalPages,
    loading,
    marking,
    selectedIds,
    selectAll,
    isIndeterminate,
    selectedCount,
    hasSelection,
    unreadCount,
    processedList,
    goToPage,
    toggleSelect,
    goBack,
    handleItemClick,
    handleBatchMarkRead,
    handleMarkAll,
    clearSelection,
  }
}
