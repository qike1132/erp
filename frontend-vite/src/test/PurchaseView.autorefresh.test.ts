import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// Hoisted mock state — vi.mock factories are hoisted to the top of the file,
// so we keep mutable mocks inside vi.hoisted() and reference them by name.
const mocks = vi.hoisted(() => ({
  ordersMock: vi.fn(),
  unprocessedMock: vi.fn(),
}))

vi.mock('@/api', () => ({
  purchaseApi: {
    orders: mocks.ordersMock,
    unprocessedOrders: mocks.unprocessedMock,
    oneClickGenerate: vi.fn(),
    completeOrder: vi.fn(),
    batchComplete: vi.fn(),
    orderDetail: vi.fn(),
    deleteOrder: vi.fn(),
    batchDelete: vi.fn(),
    updateOrder: vi.fn(),
    completed: vi.fn(),
    exportCompleted: vi.fn(),
    quickFilters: vi.fn(),
    suggestions: vi.fn(),
    factorySummary: vi.fn(),
    supplierSummary: vi.fn(),
    saveFactoryEdits: vi.fn(),
    summaryPrint: vi.fn(),
    supplierSummaryExport: vi.fn(),
    products: vi.fn(),
    searchSuggestions: vi.fn(),
    calculate: vi.fn(),
  },
}))

vi.mock('@tanstack/vue-query', async () => {
  const { ref, onScopeDispose, watchEffect } = await import('vue')
  // 模拟真实 Vue Query：挂载即执行 queryFn（否则 purchaseApi.orders 永远不会被调用），
  // 并用 watchEffect 响应式处理 refetchInterval（模拟 auto-refresh 行为）。
  const useQuery = (opts: {
    queryFn?: () => unknown
    refetchInterval?: () => number | false
  }) => {
    const data = ref<unknown>(null)
    const isLoading = ref(true)
    const isFetching = ref(false)
    const refetch = vi.fn(() => {
      if (typeof opts?.queryFn !== 'function') return Promise.resolve()
      isFetching.value = true
      return Promise.resolve()
        .then(() => opts.queryFn!())
        .then((res) => { data.value = res; isLoading.value = false; isFetching.value = false })
        .catch(() => { isLoading.value = false; isFetching.value = false })
    })
    if (typeof opts?.queryFn === 'function') {
      void refetch()
    }
    // refetchInterval: 响应式跟踪返回值，返回数字时按间隔周期调用 refetch
    if (typeof opts?.refetchInterval === 'function') {
      let timer: ReturnType<typeof setInterval> | null = null
      watchEffect(() => {
        if (timer) { clearInterval(timer); timer = null }
        const interval = opts.refetchInterval!()
        if (typeof interval === 'number' && interval > 0) {
          timer = setInterval(() => void refetch(), interval)
        }
      })
      onScopeDispose(() => { if (timer) clearInterval(timer) })
    }
    return { data, isLoading, isFetching, refetch }
  }
  return {
    useQueryClient: () => ({ invalidateQueries: vi.fn(), prefetchQuery: vi.fn() }),
    useQuery,
    keepPreviousData: {},
  }
})

vi.mock('@/composables/useToast', () => ({
  showToast: vi.fn(),
}))

vi.mock('@/composables/useConfirmDialog', () => ({
  useConfirmDialog: () => ({
    open: false,
    text: '',
    sub: '',
    type: 'warning',
    onConfirm: vi.fn(),
    onCancel: vi.fn(),
    confirm: vi.fn(async () => true),
  }),
}))

import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'

const stubs = {
  PendingOrdersPanel: { template: '<div />' },
  ActiveOrdersPanel: { template: '<div />' },
  CompletedOrdersPanel: { template: '<div />' },
  OrderDetailModal: { template: '<div />' },
  SummaryModal: { template: '<div />' },
  UiConfirmDialog: { template: '<div />' },
}

import PurchaseView from '@/views/purchase/PurchaseView.vue'

describe('PurchaseView auto-refresh orders filter (regression for BUG-PURCHASE-COUNT)', () => {
  beforeEach(() => {
    mocks.ordersMock.mockReset()
    mocks.unprocessedMock.mockReset()
    mocks.ordersMock.mockResolvedValue({ orders: [], total: 0, pages: 1, current_page: 1 })
    mocks.unprocessedMock.mockResolvedValue({ orders: [], total: 0, pages: 1, current_page: 1 })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('initial load() applies status=pending,confirmed filter', async () => {
    mount(PurchaseView, { global: { stubs } })
    await flushPromises()
    await nextTick()

    const callsWithFilter = mocks.ordersMock.mock.calls.filter(
      (args) => args[0]?.status === 'pending,confirmed',
    )
    expect(callsWithFilter.length).toBeGreaterThan(0)
  })

  it('auto-refresh callback also includes status=pending,confirmed (BUG-PURCHASE-COUNT regression guard)', async () => {
    vi.useFakeTimers()
    const wrapper = mount(PurchaseView, { global: { stubs } })
    await flushPromises()

    // Auto-refresh only calls purchaseApi.orders() on the "待生产订单" tab.
    const activeTab = wrapper.findAll('button.pc-tab-btn').find((b) => b.text().includes('待生产订单'))
    expect(activeTab, 'active tab button should exist').toBeTruthy()
    await activeTab!.trigger('click')
    await flushPromises()

    // Isolate auto-refresh-driven calls
    mocks.ordersMock.mockClear()

    // Advance past 30s to fire at least one auto-refresh cycle
    await vi.advanceTimersByTimeAsync(31_000)
    await flushPromises()

    expect(mocks.ordersMock).toHaveBeenCalled()
    // Every orders() call must include the status filter; otherwise the count
    // can drift when completed orders exist (BUG-PURCHASE-COUNT regression).
    for (const call of mocks.ordersMock.mock.calls) {
      expect(call[0]?.status).toBe('pending,confirmed')
    }
  })
})
