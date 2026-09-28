/**
 * 记录查询「查询」按钮回归测试。
 *
 * 历史缺陷：queryKey 写成 [KEY, page, { ...filters }]，展开运算符在 setup 阶段
 * 就把筛选条件固化成快照，之后点「查询」改了 filters 也不会重新请求。
 * 本测试锁定 queryKey 必须是随 filters 变化的响应式来源。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

const captured = vi.hoisted(() => ({ options: undefined as { queryKey?: unknown } | undefined }))

vi.mock('@tanstack/vue-query', async () => {
  const { ref } = await import('vue')
  return {
    useQuery: (options: { queryKey?: unknown }) => {
      captured.options = options
      return {
        data: ref(null),
        isLoading: ref(false),
        isFetching: ref(false),
        isError: ref(false),
      }
    },
    useQueryClient: () => ({ invalidateQueries: vi.fn() }),
    keepPreviousData: {},
  }
})

vi.mock('@/api', () => ({
  purchaseApi: { completed: vi.fn(), exportCompleted: vi.fn() },
}))

import { effectScope } from 'vue'
import { useCompletedOrders } from '@/views/purchase/composables/useCompletedOrders'

function runComposable() {
  const scope = effectScope()
  const instance = scope.run(() => useCompletedOrders())
  if (!instance) throw new Error('composable 未返回实例')
  return instance
}

/** 读取 queryKey 当前值；返回 undefined 说明它不是响应式来源（即缺陷形态） */
function readKey(): unknown {
  const key = captured.options?.queryKey as { value?: unknown } | undefined
  return key && typeof key === 'object' && 'value' in key ? key.value : undefined
}

beforeEach(() => {
  captured.options = undefined
})

describe('useCompletedOrders 查询条件', () => {
  it('草稿改动不触发请求，点查询后 queryKey 带入生效条件', () => {
    const orders = runComposable()
    const before = JSON.stringify(readKey())
    expect(before).toBeDefined()

    orders.draft.product_name = '咸鱼'
    expect(JSON.stringify(readKey())).toBe(before)

    orders.search()
    const after = readKey()
    expect(JSON.stringify(after)).not.toBe(before)
    expect(JSON.stringify(after)).toContain('咸鱼')
  })

  it('重置后条件从 queryKey 中清空', () => {
    const orders = runComposable()
    orders.draft.product_name = '咸鱼'
    orders.search()
    expect(JSON.stringify(readKey())).toContain('咸鱼')

    orders.reset()
    expect(JSON.stringify(readKey())).not.toContain('咸鱼')
  })
})
