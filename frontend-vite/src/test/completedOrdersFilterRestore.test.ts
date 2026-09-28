import { describe, it, expect, vi, beforeEach } from 'vitest'

// vi.mock 工厂被提升到文件顶部，可变 mock 必须放进 vi.hoisted()
const mocks = vi.hoisted(() => ({
  completedMock: vi.fn(),
  ordersMock: vi.fn(),
  unprocessedMock: vi.fn(),
  invalidateMock: vi.fn(),
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
    completed: mocks.completedMock,
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

// 真实 Vue Query 会在 queryKey 变化时重新取数；默认 mock 不模拟这点，
// 就测不出「改了条件点查询是否真的发出新请求」。此处按 queryKey 响应式重跑 queryFn。
vi.mock('@tanstack/vue-query', async () => {
  const { ref, watchEffect } = await import('vue')
  const useQuery = (opts: { queryKey?: { value: unknown }; queryFn?: () => unknown }) => {
    const data = ref<unknown>(null)
    const isLoading = ref(true)
    const isFetching = ref(false)
    const isError = ref(false)
    const run = () => {
      if (typeof opts.queryFn !== 'function') return
      isFetching.value = true
      void Promise.resolve()
        .then(() => opts.queryFn!())
        .then((res) => { data.value = res; isLoading.value = false; isFetching.value = false })
        .catch(() => { isLoading.value = false; isFetching.value = false; isError.value = true })
    }
    watchEffect(() => {
      // 读取 queryKey 建立依赖：条件/页码变化即重跑，模拟真实 refetch
      if (opts.queryKey) void opts.queryKey.value
      run()
    })
    return { data, isLoading, isFetching, isError, refetch: run }
  }
  return {
    useQueryClient: () => ({ invalidateQueries: mocks.invalidateMock, prefetchQuery: vi.fn() }),
    useQuery,
    keepPreviousData: {},
  }
})

vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))

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
import { nextTick, reactive } from 'vue'
import PurchaseView from '@/views/purchase/PurchaseView.vue'
import CompletedOrdersPanel from '@/views/purchase/components/CompletedOrdersPanel.vue'
import type { CompletedOrderFilters } from '@/views/purchase/composables/useCompletedOrders'

const stubs = {
  PendingOrdersPanel: { template: '<div />' },
  ActiveOrdersPanel: { template: '<div />' },
  CompletedOrdersPanel: { template: '<div />' },
  OrderDetailModal: { template: '<div />' },
  SummaryModal: { template: '<div />' },
  UiConfirmDialog: { template: '<div />' },
}

const EMPTY_FILTERS: CompletedOrderFilters = {
  product_name: '',
}

async function mountOnHistoryTab() {
  const wrapper = mount(PurchaseView, { global: { stubs } })
  await flushPromises()
  const tab = wrapper.findAll('button.pc-tab-btn').find((b) => b.text().includes('记录查询'))
  expect(tab, '记录查询 TAB 应存在').toBeTruthy()
  await tab!.trigger('click')
  await flushPromises()
  return wrapper
}

describe('记录查询：筛选入口回归（本次改动只保留产品名称输入）', () => {
  beforeEach(() => {
    mocks.completedMock.mockReset()
    mocks.ordersMock.mockReset()
    mocks.unprocessedMock.mockReset()
    mocks.invalidateMock.mockReset()
    mocks.completedMock.mockResolvedValue({ orders: [], total: 0, total_pages: 1 })
    mocks.ordersMock.mockResolvedValue({ orders: [], total: 0, pages: 1, current_page: 1 })
    mocks.unprocessedMock.mockResolvedValue({ orders: [], total: 0, pages: 1, current_page: 1 })
  })

  it('筛选区只提供产品名称输入，不再有订单号/客户/完成日期', async () => {
    const wrapper = await mountOnHistoryTab()

    const placeholders = wrapper.findAll('.pc-filter-input').map((i) => i.attributes('placeholder'))
    expect(placeholders).toEqual(['产品名称'])

    const dates = wrapper.findAll('input[type="date"]')
    expect(dates).toHaveLength(0)
  })

  it('填入产品名称后点查询，请求参数里带上 product_name', async () => {
    const wrapper = await mountOnHistoryTab()

    const productInput = wrapper
      .findAll('.pc-filter-input')
      .find((i) => i.attributes('placeholder') === '产品名称')!
    await productInput.setValue('白色T恤')

    const searchBtn = wrapper.findAll('button.pc-btn').find((b) => b.text() === '查询')!
    await searchBtn.trigger('click')
    await flushPromises()

    const lastParams = mocks.completedMock.mock.calls.at(-1)?.[0]
    expect(lastParams).toMatchObject({ product_name: '白色T恤' })
  })

  it('点查询总会触发一次重新取数（条件未变时 queryKey 不变，staleTime 会吞掉请求）', async () => {
    const wrapper = await mountOnHistoryTab()
    mocks.invalidateMock.mockClear()

    const searchBtn = wrapper.findAll('button.pc-btn').find((b) => b.text() === '查询')!
    await searchBtn.trigger('click')
    await flushPromises()

    expect(mocks.invalidateMock).toHaveBeenCalled()
    void wrapper
  })
})

describe('记录查询：胶囊只反映已生效条件（draft 未提交不得出现）', () => {
  const panelStubs = { UiPagination: { template: '<div />' }, FontAwesomeIcon: { template: '<i />' } }

  function mountPanel(filters: CompletedOrderFilters) {
    return mount(CompletedOrdersPanel, {
      props: {
        filters,
        orders: [],
        loading: false,
        fetching: false,
        error: false,
        total: 0,
        currentPage: 1,
        totalPages: 1,
        hasFilter: false,
      },
      global: { stubs: panelStubs },
    })
  }

  it('胶囊随已提交条件出现，条件清空后消失', async () => {
    const filters = reactive({ ...EMPTY_FILTERS, product_name: '已提交的产品' })
    const wrapper = mountPanel(filters)
    await nextTick()
    expect(wrapper.text()).toContain('已提交的产品')

    filters.product_name = ''
    await nextTick()
    expect(wrapper.text()).not.toContain('已提交的产品')
    expect(wrapper.text()).not.toContain('当前条件')
    wrapper.unmount()
  })

  it('已提交条件显示为胶囊', async () => {
    const filters = reactive({ ...EMPTY_FILTERS, product_name: '已提交的产品' })
    const wrapper = mountPanel(filters)
    await nextTick()

    expect(wrapper.text()).toContain('已提交的产品')
    wrapper.unmount()
  })
})
