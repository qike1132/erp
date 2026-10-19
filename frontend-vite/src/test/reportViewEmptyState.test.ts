/**
 * ReportView / ReportTable 空态与持久化缓存快照回归（OCR-R4，2026-10-19）。
 *
 * 缺陷一（M:114）：查询门槛初始关闭后，ReportTable 的 #empty 槽对「未查询」与
 * 「查过没结果」一律渲染「暂无数据」——用户进页面看到空表，误以为查过没数据，
 * 没有任何「需要先点查询」的引导。
 *
 * 缺陷二（M:129）：report-data 查询经 persistQueryClient 持久化到 sessionStorage，
 * F5 后 disabled 的 useQuery 仍暴露缓存 data——用户没点查询就看到旧快照行
 * （最长 24h maxAge），且无 isFetching 指示、不自动刷新。
 *
 * 修复：ReportTable 空态文案感知 searched；ReportView 的 logs/pagination 计算
 * 属性在 searched=false 时一律返回空（未查询既不渲染数据也不渲染分页）。
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

function mountTable(overrides: { searched?: boolean; isFetching?: boolean } = {}) {
  return mount(ReportTable, {
    props: {
      logs: [],
      columns: [],
      isLoading: false,
      isFetching: overrides.isFetching ?? false,
      searched: overrides.searched ?? false,
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

describe('ReportTable — 空态区分未查询（OCR-4 M:114）', () => {
  it('未查询（searched=false）：显示操作引导文案，而非「暂无数据」', () => {
    const wrapper = mountTable({ searched: false })
    expect(wrapper.find('.rp-empty span').text()).toBe('请输入查询条件后点击查询')
  })

  it('已查询且无结果（searched=true）：仍显示「暂无数据」', () => {
    const wrapper = mountTable({ searched: true })
    expect(wrapper.find('.rp-empty span').text()).toBe('暂无数据')
  })

  it('已查询且正在拉取（searched=true, isFetching=true）：显示「加载中…」（守护既有行为）', () => {
    const wrapper = mountTable({ searched: true, isFetching: true })
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
    searched: { type: Boolean, default: false },
  },
  emits: ['update:filters', 'search', 'reset', 'export'],
  template: `
    <div class="fbar">
      <input class="f-product" :value="filters.product" @input="filters.product = $event.target.value" />
      <button class="f-search" @click="$emit('search')">查询</button>
      <button v-if="searched" class="f-export" @click="$emit('export')">导出</button>
    </div>
  `,
})

/** ReportTable 替身：透出行数与分页页数（均应为未查询态的零值） */
const TableStub = defineComponent({
  name: 'TableStub',
  props: {
    logs: { type: Array, default: () => [] },
    searched: { type: Boolean, default: false },
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

/** 预填 report-data 缓存（模拟 persistQueryClient 从 sessionStorage 恢复的快照） */
const CACHED_ROWS = [
  { order_id: 1, product_name: '保温杯', quantity: 10 },
  { order_id: 1, product_name: '杯盖', quantity: 5 },
]
function seedRestoredCache(queryClient: QueryClient) {
  queryClient.setQueryData(
    ['report-data', 'order', 1, 15, { customer: '', product: '' }],
    { logs: CACHED_ROWS, pagination: { pages: 2, total: 30 } },
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

describe('ReportView — F5 持久化缓存恢复不渲染旧快照（OCR-4 M:129）', () => {
  beforeEach(() => {
    mocks.orderLogs.mockReset()
    mocks.orderLogs.mockResolvedValue({ logs: [], pagination: { pages: 1, total: 0 } })
  })

  it('缓存已恢复但未点查询（searched=false）：表格零行、分页零页，不显示旧快照', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    seedRestoredCache(queryClient)

    const wrapper = mountView(queryClient)
    await flushPromises()

    expect(wrapper.find('.t-count').text()).toBe('0')
    expect(wrapper.find('.t-pages').text()).toBe('0')
    // disabled 的查询不得发请求
    expect(mocks.orderLogs).not.toHaveBeenCalled()
  })

  it('点「查询」后：显式重查一次并正常渲染数据行（守护 gate 不挡已查询态）', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    seedRestoredCache(queryClient)

    const wrapper = mountView(queryClient)
    await flushPromises()

    // 「查询」是显式命令（M6）：即使同 key 缓存 fresh 也必须真的发一次请求
    mocks.orderLogs.mockResolvedValue({ logs: CACHED_ROWS, pagination: { pages: 2, total: 30 } })
    await wrapper.find('.f-search').trigger('click')
    await flushPromises()

    expect(mocks.orderLogs).toHaveBeenCalledTimes(1)
    expect(wrapper.find('.t-count').text()).toBe('2')
    expect(wrapper.find('.t-pages').text()).toBe('2')
  })
})