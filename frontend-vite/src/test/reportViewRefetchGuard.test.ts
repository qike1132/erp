/**
 * ReportView refetch 拒绝防御契约回归（OCR R22-L1，2026-10-20 裁决 b 修正版）。
 *
 * 契约语义：本文件锁的是组件对 refetch rejection 的【防御契约】——doSearch 里
 * `void refetch({ cancelRefetch: false }).catch(...)` 必须存在：refetch promise 一旦
 * reject 就地消化并以 console.warn('报表刷新失败', e) 留痕，绝不悬空丢弃。
 * 当前版本（@tanstack/query-core 5.100.10）的 QueryObserver 在未传 throwOnError 时
 * 以 catch(noop) 吞掉 rejection，该 catch 分支实际不可达（运行时探针实证，证据归档
 * 于任务 73）；真实查询/防抖路径由 reportViewFilterDebounce.test.ts 的真实
 * vue-query 架构覆盖，与本文件互补而非重叠。
 * 本文件用 mock useQuery 在模块边界注入「refetch 返回 rejected promise」——这是
 * query-core 将来升级改变吞错行为后组件将暴露的真实形态。有/无 .catch 两态在该
 * 注入下断言结果不同（warn 调用与否 + unhandled rejection 有无），可区分、可变异，
 * 属标准的防御性契约测试，不是镜像断言。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import { QueryClient, VueQueryPlugin, CancelledError } from '@tanstack/vue-query'

const mocks = vi.hoisted(() => ({
  orderLogs: vi.fn(),
  refetch: vi.fn(),
  // useQuery 分发点（R36-L-a）：mock 工厂把真实 useQuery 存入 realUseQuery、导出换成
  // 本 mock——R22-L1 beforeEach 覆写为注入形态（原工厂内联实现移入，行为不变），
  // R36-L-a beforeEach 恢复透传真实实现（真实 vue-query 架构才能复现「queryKey 变化
  // 不取消旧 query 的在途 fetch」）
  useQueryImpl: vi.fn(),
  realUseQuery: undefined as unknown as (...args: unknown[]) => unknown,
}))

// 只替 useQuery：keepPreviousData / useQueryClient / VueQueryPlugin 等其余导出透传真实实现。
// useReportRowActions 内部调 useQueryClient（真实），故 mount 仍须提供 VueQueryPlugin + QueryClient。
vi.mock('@tanstack/vue-query', async (importOriginal) => {
  const actual = await importOriginal()
  mocks.realUseQuery = (actual as { useQuery: unknown }).useQuery as unknown as typeof mocks.realUseQuery
  return {
    ...(actual as object),
    useQuery: mocks.useQueryImpl,
  }
})

// —— 以下模块 mock 与 reportViewFilterDebounce.test.ts 同款（真实 vue-query 架构的姊妹文件）——

// ReportView 经 useReportConfig 的 ENDPOINT_MAP 以「orderLogs」等枚举名取 reportApi 方法
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

// 上报通道单独 mock：断言 refreshReport 的留痕真的走了 reportError
// （生产构建会 drop 掉 console，只断言 console 等于没断言生产行为）
const { reportErrorMock } = vi.hoisted(() => ({ reportErrorMock: vi.fn() }))
vi.mock('@/utils/errorReporter', () => ({
  reportError: reportErrorMock,
}))

import { showToast } from '@/composables/useToast'
import ReportView from '@/views/report/ReportView.vue'

/** 真实等待：给 unhandledRejection（Node 在事件循环 turn 末触发）一个 macrotask 窗口 */
const sleep = (ms: number) => new Promise<void>((r) => { setTimeout(r, ms) })

/** ReportFilterBar 替身：与 reportViewFilterDebounce.test.ts 同款（就地 mutate filters + 同事件名） */
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
    </div>
  `,
})

/** ReportTable 最小替身：只需可渲染 */
const TableStub = defineComponent({
  name: 'TableStub',
  props: {
    logs: { type: Array, default: () => [] },
    searched: { type: Boolean, default: false },
  },
  template: `<div class="table-stub" />`,
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

describe('ReportView — refetch 拒绝防御契约（R22-L1）', () => {
  beforeEach(() => {
    mocks.orderLogs.mockReset()
    mocks.orderLogs.mockResolvedValue({ logs: [], pagination: { pages: 3, total: 40 } })
    mocks.refetch.mockReset()
    // 注入拒绝形态：refetch 一被调用即新建 rejected promise。用 mockImplementation
    // 惰性创建（而非 mockReturnValue 复用同一实例）——promise 须在组件调用 refetch 的
    // 同一同步块内诞生并即刻被 .catch 挂上，避免 mock 自身先于组件跨事件循环检查点
    // 而制造出与被测契约无关的 unhandled rejection。
    mocks.refetch.mockImplementation(() => Promise.reject(new Error('报表刷新失败-注入')))
    // R36-L-a mock 分发：本 describe 用注入形态（原 mock 工厂内联实现移到此处，行为不变）
    mocks.useQueryImpl.mockReset()
    mocks.useQueryImpl.mockImplementation(() => ({
      // ReportView 从 useQuery 解构 data / error / isLoading / isFetching / isPaused /
      // refetch（以组件代码为准）——error/isPaused 由 showRows computed 与横幅挡板读取，
      // 缺字段即 TypeError（R40 实证），mock 必须覆盖组件消费的全部解构字段
      data: ref({ logs: [], pagination: { pages: 3, total: 40 } }),
      error: ref(undefined),
      isLoading: ref(false),
      isFetching: ref(false),
      isPaused: ref(false),
      // 防御契约的注入点：refetch 返回 rejected promise，模拟 query-core 升级后
      // observer 不再吞错、rejection 直接抛给调用方的形态
      refetch: mocks.refetch,
    }))
  })

  it('提交搜索触发 refetch 拒绝：就地消化 + reportError 上报 + 零 unhandled rejection', async () => {
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const unhandled: unknown[] = []
    const onUnhandled = (r: unknown) => { unhandled.push(r) }
    process.on('unhandledRejection', onUnhandled)
    try {
      const wrapper = mountView()
      await flushPromises()

      await wrapper.find('.f-product').setValue('保温杯')
      await wrapper.find('.f-search').trigger('click') // doSearch → nextTick → refetch
      await flushPromises()
      await sleep(50)
      await flushPromises()

      // 路径确认：refetch 确实以 cancelRefetch:false 被调（doSearch 全链路走到）
      expect(mocks.refetch).toHaveBeenCalledTimes(1)
      expect(mocks.refetch).toHaveBeenCalledWith({ cancelRefetch: false })
      // 防御契约：拒绝被 .catch 消化并留痕，而非悬空
      expect(errSpy).toHaveBeenCalledWith('报表刷新失败', expect.any(Error))
      // 生产可用性：console 会被生产构建 drop 掉（vite.config.ts drop:['console']），
      // 留痕必须同时走 reportError 才能真正落到 Sentry
      expect(reportErrorMock).toHaveBeenCalledWith(
        expect.any(Error),
        expect.objectContaining({ scope: 'report.refreshReport' }),
      )
      // 悬空 rejection 必须为零（防御 .catch 存在时 promise 已被就地消化）
      expect(unhandled).toHaveLength(0)
      wrapper.unmount()
    } finally {
      process.off('unhandledRejection', onUnhandled)
      errSpy.mockRestore()
    }
  })

  it('取消类 rejection 不得上报 Sentry（登出 clear 会取消在途查询，非应用错误）', async () => {
    // auth.ts:63 登出时 queryClient.clear() 会取消在途查询 → refetch 以 CancelledError
    // reject。这不是应用错误，上报它会污染 Sentry，更糟的是 reportError 的
    // MAX_REPORTS=10 是与全局错误处理器共享的会话级配额——反复登出会把真正的
    // 渲染错误遥测额度挤光。
    mocks.refetch.mockReset()
    mocks.refetch.mockImplementation(() => Promise.reject(new CancelledError({ revert: true })))
    // 本 describe 的 beforeEach 只 reset mocks.refetch，不清 reportErrorMock——
    // 上一个用例的调用记录会残留，故在此显式清空
    reportErrorMock.mockClear()
    mocks.useQueryImpl.mockReset()
    mocks.useQueryImpl.mockImplementation(() => ({
      data: ref({ logs: [], pagination: { pages: 3, total: 40 } }),
      error: ref(undefined),
      isLoading: ref(false),
      isFetching: ref(false),
      isPaused: ref(false),
      refetch: mocks.refetch,
    }))
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

    const wrapper = mountView()
    await flushPromises()
    await wrapper.find('.f-product').setValue('保温杯')
    await wrapper.find('.f-search').trigger('click')
    await flushPromises()
    await sleep(50)
    await flushPromises()

    expect(reportErrorMock).not.toHaveBeenCalled()
    errSpy.mockRestore()
    wrapper.unmount()
  })
})

describe('ReportView — R40 错误反馈单通道（queryFn 零 toast，error 上抛归横幅）', () => {
  beforeEach(() => {
    mocks.orderLogs.mockReset()
    // 透传真实 useQuery（原 R36-L-a 口径沿用）：queryKey 隔离语义（key 变化不取消旧
    // query 的在途 fetch）只有真实 query-core 才能复现，mock useQuery 无 queryFn 可言
    mocks.useQueryImpl.mockReset()
    mocks.useQueryImpl.mockImplementation((...args: unknown[]) => mocks.realUseQuery(...args))
    vi.mocked(showToast).mockClear()
  })

  it('R40: 慢请求在途时改筛选重搜：被放弃的旧请求与当前请求失败均零 toast，error 上抛由横幅承接', async () => {
    // R40 核心方案（删 queryFn 内 toast 与 isStaleRequest 守卫）：横幅常驻后错误反馈
    // 已有持久单通道；TanStack queryKey 隔离使旧 key 的 error 属于旧 query，新 observer
    // 的横幅只读新 query 的 error——「过时请求 toast 误导」的存在前提（queryFn 内 toast）
    // 随删，手抄 queryKey 五字段的守卫（OCR-R40 L:221）整体消解。场景沿用 R36-L-a
    // 骨架：慢报表请求 A 在途时改筛选重搜，被放弃的 A 稍后失败。
    const rejecters: Array<(e: Error) => void> = []
    mocks.orderLogs.mockImplementation(
      () => new Promise((_resolve, reject) => { rejecters.push(reject) }),
    )
    const wrapper = mountView()
    await flushPromises()
    expect(mocks.orderLogs).not.toHaveBeenCalled() // 前置：查询门槛初始关闭（P1-24）

    // 查询 A（在途）：提交筛选「保温杯」
    await wrapper.find('.f-product').setValue('保温杯')
    await wrapper.find('.f-search').trigger('click')
    await flushPromises()
    expect(mocks.orderLogs).toHaveBeenCalledTimes(1)
    expect(mocks.orderLogs).toHaveBeenLastCalledWith(expect.objectContaining({ product: '保温杯' }))

    // 查询 B：改筛选「马甲」重搜——queryKey 变化只重新定位 observer，A 继续在途不被取消
    await wrapper.find('.f-product').setValue('马甲')
    await wrapper.find('.f-search').trigger('click')
    await flushPromises()
    expect(mocks.orderLogs).toHaveBeenCalledTimes(2)
    expect(mocks.orderLogs).toHaveBeenLastCalledWith(expect.objectContaining({ product: '马甲' }))

    // 被放弃的 A 稍后失败：零 toast（错误归旧 query 的 error，不进当前 observer 横幅）
    rejecters[0]!(new Error('查询A失败'))
    await flushPromises()
    await flushPromises()
    expect(showToast).not.toHaveBeenCalled()

    // 当前的 B 失败：同样零 toast（R40 单通道），error 正常上抛 → 横幅渲染 B 的错误
    // （Red：旧代码 queryFn catch 内就地 toast「查询B失败」）
    rejecters[1]!(new Error('查询B失败'))
    await flushPromises()
    await flushPromises()
    expect(showToast).not.toHaveBeenCalled()
    expect(wrapper.find('.rp-error-banner').exists()).toBe(true)
    expect(wrapper.find('.rp-error-banner').text()).toContain('查询B失败')
    // 防抖收尾：让 300ms 防抖到期消化（快照一致 no-op），不留脏计时器
    await sleep(350)
    await flushPromises()
    wrapper.unmount()
  })
})