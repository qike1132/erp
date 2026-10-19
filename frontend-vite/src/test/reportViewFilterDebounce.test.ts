/**
 * ReportView 筛选防抖与提交门槛回归（2026-10-19 审计 P1-24）。
 *
 * 缺陷：`searched = ref(true)` 门槛恒真（挂载即查、切 tab 即查），
 * 且 reactive `filters` 直接放进 queryKey——子组件（ReportFilterBar 经
 * defineModel）就地 mutate filters 对象，用户在筛选框每敲一个字符
 * queryKey 就变一次 → 每键触发一次后端查询。「查询」按钮形同虚设。
 *
 * 修复（照仓内既有模式：useDebouncedSearch 统一防抖 composable +
 * PurchasePlanView 的「防抖快照」口径）：
 *   - searched 初始 false，提交（显式点查询 / 300ms 防抖静默）后才 true；
 *   - queryKey 改用「已提交」的筛选快照 appliedFilters，而非 reactive 原对象。
 *
 * 注意：用真实定时器而非 fake timers——@tanstack/query-core 的调度在
 * fake timers 下会被冻结，挂载请求根本发不出，会制造「未请求」假绿。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

const mocks = vi.hoisted(() => ({
  orderLogs: vi.fn(),
}))

// ReportView 经 useReportConfig 的 ENDPOINT_MAP 以「orderLogs」等枚举名取 reportApi 方法
// （reportApi.orderLogs → GET /reports/order-logs），mock key 必须用枚举名而非 URL 路径。
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

/** 真实等待（防抖 300ms 的测试窗口；fake timers 会冻结 vue-query 调度，见文件头注释） */
const sleep = (ms: number) => new Promise<void>((r) => { setTimeout(r, ms) })

/**
 * ReportFilterBar 替身：与真件同机制（就地 mutate 父传入的 filters 对象属性），
 * 把「用户键入」模拟到与生产路径一致；按钮 emit 与真件同事件名。
 */
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
      <button class="f-reset" @click="$emit('reset')">重置</button>
      <button v-if="searched" class="f-export" @click="$emit('export')">导出</button>
    </div>
  `,
})

/** ReportTable 替身：透出行数；翻页按钮模拟 PrimeVue 分页事件（0 基 → 父组件 +1） */
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
      <button class="t-page2" @click="$emit('page', { page: 1, rows: 15 })">第2页</button>
    </div>
  `,
})

function mountView() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
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

describe('ReportView — 筛选防抖与提交门槛（P1-24）', () => {
  beforeEach(() => {
    mocks.orderLogs.mockReset()
    mocks.orderLogs.mockResolvedValue({ logs: [], pagination: { pages: 3, total: 40 } })
  })

  it('进入页面不发请求：查询门槛初始关闭（enabled=false）', async () => {
    mountView()
    await flushPromises()
    expect(mocks.orderLogs).not.toHaveBeenCalled()
  })

  it('连续键入三个字符：防抖窗口内零请求，停顿 300ms 后只发 1 次（不逐键请求）', async () => {
    const wrapper = mountView()
    await flushPromises()

    const input = wrapper.find('.f-product')
    await input.setValue('保')
    await input.setValue('保温')
    await input.setValue('保温杯')
    await flushPromises()
    // 防抖窗口内（最后一次键入后未满 300ms）不得有任何请求
    expect(mocks.orderLogs).not.toHaveBeenCalled()

    await sleep(400)
    await flushPromises()
    expect(mocks.orderLogs).toHaveBeenCalledTimes(1)
    expect(mocks.orderLogs).toHaveBeenCalledWith({ page: 1, per_page: 15, product: '保温杯' })
  })

  it('键入中途继续打字：防抖窗口重置，只应用最终输入', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('.f-product').setValue('保温')
    await sleep(150) // 未停满 300ms
    await wrapper.find('.f-product').setValue('保温杯')
    await sleep(150) // 从最后一次键入重新计 300ms，仍未满
    await flushPromises()
    expect(mocks.orderLogs).not.toHaveBeenCalled()

    await sleep(400)
    await flushPromises()
    expect(mocks.orderLogs).toHaveBeenCalledTimes(1)
    expect(mocks.orderLogs).toHaveBeenCalledWith(expect.objectContaining({ product: '保温杯' }))
  })

  it('点「查询」立即提交（不等防抖），且之后防抖到期不重复请求', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('.f-product').setValue('保温杯')
    await wrapper.find('.f-search').trigger('click')
    await flushPromises()
    expect(mocks.orderLogs).toHaveBeenCalledTimes(1)
    expect(mocks.orderLogs).toHaveBeenCalledWith(expect.objectContaining({ product: '保温杯' }))

    // 挂起的防抖回调到期：同快照提交应为 no-op，不得发出第 2 次请求
    await sleep(400)
    await flushPromises()
    expect(mocks.orderLogs).toHaveBeenCalledTimes(1)
  })

  it('提交后翻到第 2 页，再改筛选并防抖提交：回到第 1 页（新筛选从第一页看起）', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('.f-product').setValue('保温杯')
    await wrapper.find('.f-search').trigger('click')
    await flushPromises()
    expect(mocks.orderLogs).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, product: '保温杯' }))

    // 翻到第 2 页（PrimeVue 事件 0 基 → onPageChange +1）
    await wrapper.find('.t-page2').trigger('click')
    await flushPromises()
    expect(mocks.orderLogs).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2, product: '保温杯' }))

    // 改筛选词「杯」：防抖提交后必须回第 1 页
    await wrapper.find('.f-product').setValue('杯')
    await sleep(400)
    await flushPromises()
    expect(mocks.orderLogs).toHaveBeenLastCalledWith({ page: 1, per_page: 15, product: '杯' })
  })

  it('重置：清空筛选并回到第 1 页', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('.f-product').setValue('保温杯')
    await wrapper.find('.f-search').trigger('click')
    await flushPromises()
    expect(mocks.orderLogs).toHaveBeenLastCalledWith(expect.objectContaining({ product: '保温杯' }))

    await wrapper.find('.f-reset').trigger('click')
    await flushPromises()
    expect(mocks.orderLogs).toHaveBeenLastCalledWith({ page: 1, per_page: 15 })
  })

  it('导出按钮跟随查询门槛：未提交不渲染，提交后出现', async () => {
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.find('.f-export').exists()).toBe(false)

    await wrapper.find('.f-product').setValue('保温杯')
    await wrapper.find('.f-search').trigger('click')
    await flushPromises()
    expect(wrapper.find('.f-export').exists()).toBe(true)
  })
})