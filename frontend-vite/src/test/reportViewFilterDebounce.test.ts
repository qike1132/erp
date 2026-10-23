/**
 * ReportView 筛选防抖回归（2026-10-19 审计 P1-24；2026-10-23 owner 改为进页面自动查询）。
 *
 * 缺陷：reactive `filters` 直接放进 queryKey——子组件（ReportFilterBar 经
 * defineModel）就地 mutate filters 对象，用户在筛选框每敲一个字符
 * queryKey 就变一次 → 每键触发一次后端查询。
 *
 * 修复（照仓内既有模式：useDebouncedSearch 统一防抖 composable +
 * PurchasePlanView 的「防抖快照」口径）：queryKey 改用「已提交」的筛选快照
 * appliedFilters，而非 reactive 原对象。
 *
 * 2026-10-23：owner 要求进路由即见流水数据，故移除 P1-24 的 searched 查询门槛
 * （挂载即查）。防抖快照仍在——挂载只发一次，不存在逐键请求。
 *
 * 注意：用真实定时器而非 fake timers——@tanstack/query-core 的调度在
 * fake timers 下会被冻结，挂载请求根本发不出，会制造「未请求」假绿。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
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
  },
  emits: ['update:filters', 'search', 'reset', 'export'],
  template: `
    <div class="fbar">
      <input class="f-product" :value="filters.product" @input="filters.product = $event.target.value" />
      <button class="f-search" @click="$emit('search')">查询</button>
      <button class="f-reset" @click="$emit('reset')">重置</button>
      <button class="f-export" @click="$emit('export')">导出</button>
    </div>
  `,
})

/** ReportTable 替身：透出行数；翻页按钮模拟 PrimeVue 分页事件（0 基 → 父组件 +1） */
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

/**
 * 挂载并消费首屏自动查询，再清空调用记录——后续用例只计
 * 「防抖 / 显式提交」触发的请求，首屏那次由专门的用例锁定。
 */
async function mountSettled() {
  const wrapper = mountView()
  await flushPromises()
  mocks.orderLogs.mockClear()
  return wrapper
}

describe('ReportView — 筛选防抖与提交语义', () => {
  beforeEach(() => {
    mocks.orderLogs.mockReset()
    mocks.orderLogs.mockResolvedValue({ logs: [], pagination: { pages: 3, total: 40 } })
  })

  it('进入页面自动查询一次（不需要先点「查询」）', async () => {
    mountView()
    await flushPromises()
    expect(mocks.orderLogs).toHaveBeenCalledTimes(1)
    expect(mocks.orderLogs).toHaveBeenCalledWith({ page: 1, per_page: 15 })
  })

  it('连续键入三个字符：防抖窗口内零请求，停顿 300ms 后只发 1 次（不逐键请求）', async () => {
    const wrapper = await mountSettled()

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
    const wrapper = await mountSettled()

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
    const wrapper = await mountSettled()

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
    const wrapper = await mountSettled()

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

  it('重置：清空筛选并回到第 1 页（命中首屏缓存时不重复请求）', async () => {
    const wrapper = await mountSettled()

    await wrapper.find('.f-product').setValue('保温杯')
    await wrapper.find('.f-search').trigger('click')
    await flushPromises()
    expect(mocks.orderLogs).toHaveBeenLastCalledWith(expect.objectContaining({ product: '保温杯' }))

    await wrapper.find('.f-reset').trigger('click')
    await flushPromises()
    // 空筛选 key 在进页面自动查询时已取过数且仍在 staleTime 内 → 直接复用，不再发请求
    expect(mocks.orderLogs).toHaveBeenCalledTimes(1)
    expect((wrapper.vm as unknown as { page: number }).page).toBe(1)
  })

  it('导出按钮常驻：进页面即可导出（不再依赖查询门槛）', async () => {
    const wrapper = await mountSettled()

    expect(wrapper.find('.f-export').exists()).toBe(true)
  })
})
describe('ReportView — OCR-3 修复（防抖回跳 M5 / 查询空操作 M6）', () => {
  beforeEach(() => {
    mocks.orderLogs.mockReset()
    mocks.orderLogs.mockResolvedValue({ logs: [], pagination: { pages: 3, total: 40 } })
  })

  it('M5: 显式提交后 300ms 内翻页：挂起的防抖到期不得把页码打回第 1 页', async () => {
    const wrapper = await mountSettled()

    await wrapper.find('.f-product').setValue('保温杯')
    await wrapper.find('.f-search').trigger('click') // 显式提交：page=1，立即请求
    await flushPromises()
    expect(mocks.orderLogs).toHaveBeenCalledTimes(1)

    // 300ms 防抖窗口内翻到第 2 页
    await wrapper.find('.t-page2').trigger('click')
    await flushPromises()
    expect(mocks.orderLogs).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 }))

    await sleep(400) // 挂起的防抖回调此刻到期
    await flushPromises()
    // 不得回跳：page 仍停在第 2 页（当前实现无条件 page=1；回到旧 key 时因 staleTime
    // 内 fresh 可能连请求都不发，故断言 UI 状态而非请求数，直击回跳本质）
    expect((wrapper.vm as unknown as { page: number }).page).toBe(2)
    expect(mocks.orderLogs).toHaveBeenCalledTimes(2)
  })

  it('M6: 条件与页码都未变时重复点「查询」：必须真的再发一次请求', async () => {
    const wrapper = await mountSettled()

    await wrapper.find('.f-product').setValue('保温杯')
    await wrapper.find('.f-search').trigger('click')
    await flushPromises()
    expect(mocks.orderLogs).toHaveBeenCalledTimes(1)

    // 同条件同页码再点「查询」：key 哈希不变 + staleTime 30s → 静默不查（Red）；
    // 「查询」是显式命令，必须每次都真的发一次请求（参照 useCompletedOrders.search 语义）
    await wrapper.find('.f-search').trigger('click')
    await flushPromises()
    expect(mocks.orderLogs).toHaveBeenCalledTimes(2)
  })
})
describe('ReportView — OCR-4 修复（page≥2 重查 M:223 / 导出快照一致性 Low:247）', () => {
  let openSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    mocks.orderLogs.mockReset()
    mocks.orderLogs.mockResolvedValue({ logs: [], pagination: { pages: 3, total: 40 } })
    openSpy = vi.spyOn(window, 'open').mockImplementation(() => null)
  })

  afterEach(() => {
    openSpy.mockRestore()
  })

  it('M:223: 第 2 页 + 条件未变时点「查询」：必须真的再发一次请求（不许静默吃缓存）', async () => {
    const wrapper = await mountSettled()

    await wrapper.find('.f-product').setValue('保温杯')
    await wrapper.find('.f-search').trigger('click')
    await flushPromises()
    expect(mocks.orderLogs).toHaveBeenCalledTimes(1)

    // 翻到第 2 页（30s staleTime 内，page-1 缓存仍是 fresh）
    await wrapper.find('.t-page2').trigger('click')
    await flushPromises()
    expect(mocks.orderLogs).toHaveBeenCalledTimes(2)
    expect(mocks.orderLogs).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 }))

    // 条件未变、停在第 2 页时点「查询」：当前实现 unchanged 要求 page===1 → 跳过
    // refetch；commitFilters 把页码归 1 后 key 切回 page-1 的 fresh 缓存 → 静默零请求。
    // 「查询」是显式命令，必须重新拿最新数据
    await wrapper.find('.f-search').trigger('click')
    await flushPromises()
    expect(mocks.orderLogs).toHaveBeenCalledTimes(3)
    expect(mocks.orderLogs).toHaveBeenLastCalledWith({ page: 1, per_page: 15, product: '保温杯' })
  })

  it('Low:247: 草稿与已提交快照不一致时点「导出」：导出口径必须等于输入框当前所见', async () => {
    const wrapper = await mountSettled()

    await wrapper.find('.f-product').setValue('保温杯')
    await wrapper.find('.f-search').trigger('click') // 提交「保温杯」
    await flushPromises()
    expect(mocks.orderLogs).toHaveBeenCalledTimes(1)

    // 改草稿为「杯」但不等 300ms 防抖提交，立即点「导出」：
    // 当前实现读已提交快照「保温杯」→ 导出文件与输入框所见不一致（Red）
    await wrapper.find('.f-product').setValue('杯')
    await wrapper.find('.f-export').trigger('click')

    expect(openSpy).toHaveBeenCalledTimes(1)
    const url = openSpy.mock.calls[0][0] as string
    expect(url).toContain('product=%E6%9D%AF') // 「杯」——与输入框所见一致
    expect(url).toContain('report_type=order')

    // 导出提交草稿触发一次查询；挂起的防抖到期发现快照已一致 → no-op，不重复请求
    await sleep(400)
    await flushPromises()
    expect(mocks.orderLogs).toHaveBeenCalledTimes(2)
    expect(mocks.orderLogs).toHaveBeenLastCalledWith(expect.objectContaining({ product: '杯' }))
  })
})