/**
 * M8 回归锁：批量标记已读不得「假成功」。
 *
 * 背景（2026-10-26 上线前检查 M8）
 * -------------------------------
 * `notificationApi.markBatchAsRead` 用 `Promise.allSettled` 逐条调用后折叠成
 * `{ success: markedCount > 0 }`，**永不 reject**；组合式函数 await 后无条件清空
 * 选择，页面再提示「已标记 N 条为已读」。实际可能只成功 1 条甚至全部失败——
 * 未读徽章与列表从此对不上，用户以为处理完了。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { effectScope, nextTick } from 'vue'

const markBatch = vi.fn()
const markAll = vi.fn()
const markOne = vi.fn()
const fetchNotificationList = vi.fn()

vi.mock('@/api/notification', () => ({
  notificationApi: {
    markBatchAsRead: (...a: unknown[]) => markBatch(...a),
    markAllAsRead: (...a: unknown[]) => markAll(...a),
    markAsRead: (...a: unknown[]) => markOne(...a),
  },
}))

vi.mock('@/composables/notificationMemoryCache', () => ({
  clearNotificationMemoryCache: vi.fn(),
  fetchNotificationList: (...a: unknown[]) => fetchNotificationList(...a),
  getNotificationMemorySnapshot: vi.fn(() => null),
}))

import { useNotificationCenter } from '@/composables/useNotificationCenter'

const ITEMS = [
  { id: 1, is_read: false },
  { id: 2, is_read: false },
  { id: 3, is_read: false },
]

async function setup() {
  const scope = effectScope()
  const api = scope.run(() => useNotificationCenter())!
  await api.fetchList()
  return { api, scope }
}

describe('useNotificationCenter.markBatchAsRead（M8）', () => {
  beforeEach(() => {
    markBatch.mockReset()
    markAll.mockReset()
    markOne.mockReset()
    fetchNotificationList.mockReset().mockResolvedValue({
      data: ITEMS.map((n) => ({ ...n })), total: 3,
    })
  })

  it('全部成功：清空选择、条目移出列表', async () => {
    const { api, scope } = await setup()
    markBatch.mockResolvedValue({
      success: true, marked_count: 3, failed_count: 0, failed_ids: [],
    })

    await api.markBatchAsRead([1, 2, 3])
    await nextTick()

    expect(api.list.value).toHaveLength(0)
    expect(api.selectedIds.value.size).toBe(0)
    scope.stop()
  })

  it('部分失败：回滚失败项并抛出带计数的错误（不再静默成功）', async () => {
    const { api, scope } = await setup()
    markBatch.mockResolvedValue({
      success: false, marked_count: 2, failed_count: 1, failed_ids: [2],
    })

    await expect(api.markBatchAsRead([1, 2, 3])).rejects.toThrow(/已标记 2 条，1 条失败/)

    // 成功的 1、3 保持已读并留在列表外；失败的 2 回到列表且仍为未读
    expect(api.list.value.map((n) => n.id)).toEqual([2])
    expect(api.list.value[0]!.is_read).toBe(false)
    // total 是「未读数」：2 条已成功标记，只剩 1 条未读
    expect(api.total.value).toBe(1)
    scope.stop()
  })

  it('全部失败：全部回滚并抛错', async () => {
    const { api, scope } = await setup()
    markBatch.mockResolvedValue({
      success: false, marked_count: 0, failed_count: 3, failed_ids: [1, 2, 3],
    })

    await expect(api.markBatchAsRead([1, 2, 3])).rejects.toThrow()

    expect(api.list.value.map((n) => n.id).sort()).toEqual([1, 2, 3])
    expect(api.total.value).toBe(3)
    expect(api.list.value.every((n) => !n.is_read)).toBe(true)
    scope.stop()
  })

  it('请求整体失败（网络）：全部回滚', async () => {
    const { api, scope } = await setup()
    markBatch.mockRejectedValue(new Error('network'))

    await expect(api.markBatchAsRead([1, 2])).rejects.toThrow('network')

    expect(api.list.value).toHaveLength(3)
    scope.stop()
  })
})
