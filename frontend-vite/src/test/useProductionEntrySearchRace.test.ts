/**
 * H7 回归锁：生产录入的产品搜索必须丢弃过期响应。
 *
 * 背景（2026-10-26 上线前检查 H7）
 * -------------------------------
 * `onSearchInput()` 没有请求序号：先发的慢响应会覆盖后发的新结果。而
 * `confirmSearchSelection()` 在用户没按过 ↑↓ 时默认选**第一条**——于是
 * 「输入 A → 输入 AB → 回车」可能落成「A 的第一条」，录入一个与输入框
 * 内容毫不相干的产品（数量还会记到它头上）。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { defineComponent, h, ref, computed } from 'vue'
import { mount } from '@vue/test-utils'

const productSearch = vi.fn()
const productInfo = vi.fn()

vi.mock('@/api', () => ({
  customerApi: { activeNames: async () => [] },
  dailyProductionApi: {
    productInfo: (...a: unknown[]) => productInfo(...a),
    records: async () => ({ items: [], total: 0 }),
  },
  productApi: { search: (...a: unknown[]) => productSearch(...a) },
}))

vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))

vi.mock('@tanstack/vue-query', () => ({
  useQuery: () => ({ data: ref([]) }),
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))

import { useProductionEntry } from '@/views/production/composables/useProductionEntry'

function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((r) => { resolve = r })
  return { promise, resolve }
}

function setup() {
  const open = computed({
    get: () => true,
    set: () => {},
  }) as unknown as Parameters<typeof useProductionEntry>[0]
  const date = computed({
    get: () => '2026-10-26',
    set: () => {},
  }) as unknown as Parameters<typeof useProductionEntry>[1]

  let result!: ReturnType<typeof useProductionEntry>
  mount(defineComponent({
    setup() {
      result = useProductionEntry(open, date)
      return () => h('div')
    },
  }))
  return result
}

describe('useProductionEntry 搜索竞态（H7）', () => {
  beforeEach(() => {
    productSearch.mockReset()
    productInfo.mockReset().mockResolvedValue({ data: { price: 1 } })
    vi.useFakeTimers()
  })
  afterEach(() => vi.useRealTimers())

  it('旧关键字的慢响应不得覆盖新结果', async () => {
    const entry = setup()
    const first = deferred<{ id: number; name: string }[]>()
    const second = deferred<{ id: number; name: string }[]>()
    productSearch.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)

    entry.searchQuery.value = 'A'
    entry.onSearchInput()
    await vi.advanceTimersByTimeAsync(300)

    entry.searchQuery.value = 'AB'
    entry.onSearchInput()
    await vi.advanceTimersByTimeAsync(300)

    second.resolve([{ id: 2, name: 'AB-产品' }])
    await vi.advanceTimersByTimeAsync(0)
    first.resolve([{ id: 1, name: 'A-产品' }])
    await vi.advanceTimersByTimeAsync(0)

    expect(entry.searchResults.value).toEqual([{ id: 2, name: 'AB-产品' }])
  })

  it('回车默认选第一条时，选中的必须是当前关键字的结果', async () => {
    const entry = setup()
    const first = deferred<{ id: number; name: string }[]>()
    const second = deferred<{ id: number; name: string }[]>()
    productSearch.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)

    entry.searchQuery.value = 'A'
    entry.onSearchInput()
    await vi.advanceTimersByTimeAsync(300)
    entry.searchQuery.value = 'AB'
    entry.onSearchInput()
    await vi.advanceTimersByTimeAsync(300)

    // 乱序返回：新结果先到，旧结果后到
    second.resolve([{ id: 2, name: 'AB-产品' }])
    await vi.advanceTimersByTimeAsync(0)
    first.resolve([{ id: 1, name: 'A-产品' }])
    await vi.advanceTimersByTimeAsync(0)

    entry.confirmSearchSelection()
    await vi.advanceTimersByTimeAsync(0)

    expect(entry.form.product_id).toBe(2)
    expect(entry.form.product_name).toBe('AB-产品')
  })

  it('清空输入后在途响应不得把下拉重新填满', async () => {
    const entry = setup()
    const pending = deferred<{ id: number; name: string }[]>()
    productSearch.mockReturnValueOnce(pending.promise)

    entry.searchQuery.value = 'ABC'
    entry.onSearchInput()
    await vi.advanceTimersByTimeAsync(300)

    entry.searchQuery.value = ''
    entry.onSearchInput()
    pending.resolve([{ id: 1, name: 'ABC-产品' }])
    await vi.advanceTimersByTimeAsync(0)

    expect(entry.searchResults.value).toEqual([])
    expect(entry.showDropdown.value).toBe(false)
    expect(entry.searchLoading.value).toBe(false)
  })
})
