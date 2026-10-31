/**
 * 批次查询的「输入防抖 + 键只放原始值」（2026-10-30 审计 A-M37）
 *
 * 现场：queryKey 直接塞了 reactive 的 filters，每敲一个字都换一次 key → 触发一次
 * 主查询；而主查询一次要翻最多 20 页 × 500 行。用户输入「1234」= 4 次全量翻页。
 * 修复：输入文本（filters.keyword）与已应用关键字（appliedKeyword）分离，
 * 关键字走 400ms 防抖，键里只放原始值与已应用值。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { nextTick } from 'vue'

const mocks = vi.hoisted(() => ({
  batchListMock: vi.fn(),
  captured: null as null | Record<string, unknown>,
}))

vi.mock('@/api', () => ({
  batchApi: { list: mocks.batchListMock },
  orderBatchApi: { whitelist: vi.fn(async () => ({ customers: [] })) },
  customerApi: { activeNames: vi.fn(async () => []) },
}))

vi.mock('@/composables/useToast', () => ({
  showToast: vi.fn(),
}))

vi.mock('@tanstack/vue-query', async () => {
  const { ref } = await import('vue')
  return {
    useQuery: (opts: Record<string, unknown>) => {
      if ((opts.queryKey as unknown[])?.[0] === 'batch-query') {
        mocks.captured = opts
      }
      return {
        data: ref(null),
        isLoading: ref(false),
        isFetching: ref(false),
        isError: ref(false),
        refetch: vi.fn(),
      }
    },
    keepPreviousData: {},
  }
})

import { useBatchQuery } from '@/views/batch/composables/useBatchQuery'

/** 求值 queryKey（vue-query 允许键里放 getter） */
function keyValues(): unknown[] {
  const key = mocks.captured!.queryKey as unknown[]
  return key.map((part) => (typeof part === 'function' ? (part as () => unknown)() : part))
}

describe('useBatchQuery 关键字防抖与查询键', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    mocks.captured = null
    mocks.batchListMock.mockResolvedValue({ success: true, total: 0, data: [] })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('查询键里不出现 reactive 的 filters 对象', () => {
    const { filters } = useBatchQuery()

    expect(mocks.captured).not.toBeNull()
    // 键里若塞了 reactive 对象，任何字段变化都会换键 → 每次击键触发全量查询
    expect(mocks.captured!.queryKey as unknown[]).not.toContain(filters)
  })

  it('输入关键字不会立即换键，防抖到点后才生效', async () => {
    const { filters } = useBatchQuery()

    filters.keyword = 'abcd'
    await nextTick()
    expect(keyValues().at(-1)).toBe('')

    vi.advanceTimersByTime(400)
    await nextTick()
    expect(keyValues().at(-1)).toBe('abcd')
  })

  it('连续输入只把最后一次带进查询', async () => {
    const { filters } = useBatchQuery()

    filters.keyword = 'a'
    await nextTick()
    vi.advanceTimersByTime(100)
    filters.keyword = 'ab'
    await nextTick()
    vi.advanceTimersByTime(100)
    filters.keyword = 'abc'
    await nextTick()
    vi.advanceTimersByTime(400)
    await nextTick()

    expect(keyValues().at(-1)).toBe('abc')
  })

  it('「查询」按钮立即应用当前输入（不等防抖窗口）', async () => {
    const { filters, applyFilters } = useBatchQuery()

    filters.keyword = 'PO-2026'
    applyFilters()
    await nextTick()

    expect(keyValues().at(-1)).toBe('PO-2026')
  })

  it('queryFn 只发送已应用的关键字', async () => {
    const { filters, applyFilters } = useBatchQuery()

    filters.keyword = '未应用'
    await (mocks.captured!.queryFn as () => Promise<unknown>)()
    // 未应用的关键字不能进请求：否则「已应用」这层语义就没了
    expect(mocks.batchListMock.mock.calls[0]![0]).not.toHaveProperty('keyword')

    applyFilters()
    mocks.batchListMock.mockClear()
    await (mocks.captured!.queryFn as () => Promise<unknown>)()
    expect(mocks.batchListMock).toHaveBeenCalledWith(expect.objectContaining({ keyword: '未应用' }))
  })

  it('其它筛选（客户/批次/状态）仍即时生效', async () => {
    const { filters } = useBatchQuery()

    filters.customer = '贝乐'
    filters.status = 'pending'
    await nextTick()

    const values = keyValues()
    expect(values).toContain('贝乐')
    expect(values).toContain('pending')
  })
})
