/**
 * ReportView / ReportTable 空态与持久化缓存快照回归（OCR-R4，2026-10-19；
 * 2026-10-23 owner 要求改为进路由自动查询）。
 *
 * 现行行为：/report 挂载即发查询（无 searched 门槛），空态只有「加载中…」与
 * 「暂无数据」两种；F5 恢复的过期快照由挂载自动重查覆盖，用户不必再点「查询」。
 *
 * 缓存测试用 setQueryData 预填同一 queryKey 模拟「F5 后持久化恢复」——
 * queryKey 里的 ref（activeTab/page/appliedFilters）经 vue-query 解包后的
 * 形态即 ['report-data', 'order', 1, 15, { customer, product }]。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

const mocks = vi.hoisted(() => ({
  orderLogs: vi.fn(),
}))

vi.mock('@/api', () => ({
  reportApi: { orderLogs: mocks.orderLogs },
  orderApi: {},
  stockApi: {},
  stockReturnApi: {},
  auxApi: {},
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ hasPermission: () => false, hasAnyPermission: () => false }),
}))

vi.mock('@/stores/catalog', () => ({
  useCatalogStore: () => ({
    activeCustomerNames: [],
    ensureActiveCustomerNames: vi.fn(async () => {}),
  }),
}))

vi.mock('@/composables/useToast', () => ({
  showToast: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

vi.mock('@/composables/useConfirmDialog', () => ({
  useConfirmDialog: () => ({
    open: false, text: '', sub: '', type: 'warning',
    onConfirm: vi.fn(), onCancel: vi.fn(), confirm: vi.fn(async () => true),
  }),
}))

vi.mock('@/utils/queryKeys', () => ({
  invalidateOrderDerivedQueries: vi.fn(),
}))

import ReportView from '@/views/report/ReportView.vue'
import ReportTable from '@/views/report/components/ReportTable.vue'
import { TAB_CONFIG } from '@/views/report/composables/useReportConfig'

/* ------------------------------------------------------------------ */
/* 修复一：ReportTable 空态文案区分「未查询」与「查过没结果」            */
/* ------------------------------------------------------------------ */

/** UiDataTable 替身：只透传 #empty 槽——被测行为是空态文案，不需要真表格 */
const DataTableStub = defineComponent({
  name: 'DataTableStub',
  template: `<div class="dt-stub"><slot name="empty" /></div>`,
})

function mountTable(overrides: { isFetching?: boolean } = {}) {
  return mount(ReportTable, {
    props: {
      logs: [],
      columns: [],
      isLoading: false,
      isFetching: overrides.isFetching ?? false,
      perPage: 15,
      pagination: undefined,
      currentCfg: TAB_CONFIG.order,
      activeTab: 'order',
    },
    global: {
      stubs: {
        UiDataTable: DataTableStub,
        FontAwesomeIcon: true,
      },
    },
  })
}

describe('ReportTable — 空态文案', () => {
  it('无数据：显示「暂无数据」', () => {
    const wrapper = mountTable()
    expect(wrapper.find('.rp-empty span').text()).toBe('暂无数据')
  })

  it('正在拉取：显示「加载中…」', () => {
    const wrapper = mountTable({ isFetching: true })
    expect(wrapper.find('.rp-empty span').text()).toBe('加载中…')
  })
})

/* ------------------------------------------------------------------ */
/* 修复二：F5 持久化缓存恢复后，未查询不渲染旧快照                      */
/* ------------------------------------------------------------------ */

/** ReportFilterBar 替身：与真件同事件名（见 reportViewFilterDebounce.test.ts） */
const FilterBarStub = defineComponent({
  name: 'FilterBarStub',
  props: {
    filters: { type: Object, required: true },
    customerOptions: { type: Array, default: () => [] },
  },
  emits: ['update:filters', 'search', 'reset', 'export'],
  template: `
    <div class="fbar">
      <input class="f-product" :value="filters.product" @input="filters.product = $event.target.value" />
      <button class="f-search" @click="$emit('search')">查询</button>
      <button class="f-export" @click="$emit('export')">导出</button>
    </div>
  `,
})

/** ReportTable 替身：透出行数与分页页数 */
const TableStub = defineComponent({
  name: 'TableStub',
  props: {
    logs: { type: Array, default: () => [] },
    pagination: { type: Object, default: undefined },
  },
  emits: ['page'],
  template: `
    <div class="table-stub">
      <span class="t-count">{{ logs.length }}</span>
      <span class="t-pages">{{ pagination?.pages ?? 0 }}</span>
    </div>
  `,
})

/** 预填 report-data 缓存（模拟 persistQueryClient 从 sessionStorage 恢复的过期快照） */
const CACHED_ROWS = [
  { order_id: 1, product_name: '保温杯', quantity: 10 },
  { order_id: 1, product_name: '杯盖', quantity: 5 },
]
function seedRestoredCache(queryClient: QueryClient) {
  queryClient.setQueryData(
    ['report-data', 'order', 1, 15, { customer: '', product: '' }],
    { logs: CACHED_ROWS, pagination: { pages: 2, total: 30 } },
    // 超过组件 staleTime(30s)：挂载时自动重查
    { updatedAt: Date.now() - 60_000 },
  )
}

function mountView(queryClient: QueryClient) {
  return mount(ReportView, {
    global: {
      plugins: [[VueQueryPlugin, { queryClient }]],
      stubs: {
        ReportFilterBar: FilterBarStub,
        ReportTable: TableStub,
        ReportTabGroup: true,
        EditOrderItemModal: true,
        EditStockinModal: true,
        EditStockoutModal: true,
        EditReturnModal: true,
        UiConfirmDialog: true,
      },
    },
  })
}

describe('ReportView — 进页面自动查询（2026-10-23 owner 要求）', () => {
  beforeEach(() => {
    mocks.orderLogs.mockReset()
    mocks.orderLogs.mockResolvedValue({ logs: [], pagination: { pages: 1, total: 0 } })
  })

  it('无需点「查询」：挂载即发一次查询', async () => {
    const wrapper = mountView(new QueryClient({ defaultOptions: { queries: { retry: false } } }))
    await flushPromises()

    expect(mocks.orderLogs).toHaveBeenCalledTimes(1)
    expect(mocks.orderLogs).toHaveBeenCalledWith({ page: 1, per_page: 15 })
    expect(wrapper.find('.t-count').text()).toBe('0')
  })

  it('F5 恢复的过期快照：自动重查并用新结果覆盖，不等用户点查询', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    seedRestoredCache(queryClient)

    const wrapper = mountView(queryClient)
    await flushPromises()

    expect(mocks.orderLogs).toHaveBeenCalledTimes(1)
    expect(wrapper.find('.t-count').text()).toBe('0')
    expect(wrapper.find('.t-pages').text()).toBe('1')
  })
})