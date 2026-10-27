/**
 * OutsourcePresetTab 工序预设取数分页回归（2026-10-19 审计 P1-23）。
 *
 * 缺陷：`outsourceApi.processTypes({ per_page: 500 })` 单页取数、不翻页、
 * 不校验 total——预设记录超过 500 后，多出来的产品卡静默缺失（用户无感知）。
 *
 * 修复：照 useOrderImport.fetchAllStaged 的模式分页取全（每页 500，页不满即止，
 * 页数护栏防异常响应死循环）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

vi.mock('@/api/outsource', () => ({
  outsourceApi: {
    processTypes: vi.fn(),
    deleteProcessType: vi.fn(),
  },
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ hasPermission: () => false }),
}))

vi.mock('@/composables/useToast', () => ({
  showToast: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

import { outsourceApi } from '@/api/outsource'
import { toast } from '@/composables/useToast'
import type { OutsourceProcessType } from '@/api/outsource'
import OutsourcePresetTab from '@/views/outsource/components/OutsourcePresetTab.vue'

/** 与组件内一致的取数口径（断言参数用，勿复制漂移：本测试就是锁它的） */
const PAGE_SIZE = 500

/** 搜索选中的待配置产品（OutsourcePresetView 经 props 传入，拉取失败时仍存在） */
interface PendingProduct {
  product_id: number
  product_name: string
  product_barcode: string | null
  factory: string | null
}

function genPresets(idBase: number, count: number, productIdBase: number): OutsourceProcessType[] {
  return Array.from({ length: count }, (_, i) => ({
    id: idBase + i,
    product_id: productIdBase + i,
    product_name: `产品${productIdBase + i}`,
    product_barcode: null,
    factory: null,
    process_type: '电绣',
    sort_order: 0,
    is_active: true,
  }))
}

function ok(data: OutsourceProcessType[]) {
  return { success: true, data, total: data.length }
}

function mountTab(
  pendingProducts: PendingProduct[] = [],
  seed?: { items: OutsourceProcessType[]; partial: string },
) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  if (seed) queryClient.setQueryData(['outsource-process-types'], seed)
  return mount(OutsourcePresetTab, {
    props: { pendingProducts },
    global: {
      plugins: [[VueQueryPlugin, { queryClient }]],
      stubs: {
        OutsourceAddProcessDialog: true,
        UiConfirmDialog: true,
        UiSpinner: true,
      },
    },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('OutsourcePresetTab — 工序预设分页取全（P1-23）', () => {
  it('记录超过单页 500 条时自动翻页取全，产品卡不静默缺失', async () => {
    const page1 = genPresets(1, PAGE_SIZE, 1)
    const page2 = genPresets(501, 120, 501)
    // total=全量总数（分页元数据），非当页条数——total 收口口径（OCR-3）依赖它判断是否取完
    vi.mocked(outsourceApi.processTypes).mockImplementation(async (params?: { page?: number }) => ({
      success: true,
      data: params?.page === 2 ? page2 : page1,
      total: PAGE_SIZE + 120,
    }))

    const wrapper = mountTab()
    await flushPromises()

    // 620 条预设（500 + 120）必须全部到达并渲染成 620 张产品卡
    expect(outsourceApi.processTypes).toHaveBeenCalledTimes(2)
    expect(outsourceApi.processTypes).toHaveBeenNthCalledWith(1, { page: 1, per_page: PAGE_SIZE })
    expect(outsourceApi.processTypes).toHaveBeenNthCalledWith(2, { page: 2, per_page: PAGE_SIZE })
    expect(wrapper.findAll('tbody tr')).toHaveLength(620)
  })

  it('首页不满 500 条时不再请求第二页', async () => {
    vi.mocked(outsourceApi.processTypes).mockImplementation(async () => ok(genPresets(1, 3, 1)))

    const wrapper = mountTab()
    await flushPromises()

    expect(outsourceApi.processTypes).toHaveBeenCalledTimes(1)
    expect(outsourceApi.processTypes).toHaveBeenCalledWith({ page: 1, per_page: PAGE_SIZE })
    expect(wrapper.findAll('tbody tr')).toHaveLength(3)
  })

  it('护栏：每页恒满 500 时最多拉 20 页，不死循环', async () => {
    // 恒满页：全部条目同属一个产品（同 product_id 的 500 道工序），
    // 既模拟异常响应又把产品卡压到 1 行；但该行的工序 chips 仍要渲染
    // 20×500=10000 个，jsdom 下成本可观，放宽超时避免环境波动误报。
    // 响应不带 total（total 收口失效的异常形态）→ 只能靠页数护栏兜底。
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const sameProductPage = Array.from({ length: PAGE_SIZE }, (_, i) => ({
      ...genPresets(i + 1, 1, 1)[0]!,
    }))
    vi.mocked(outsourceApi.processTypes).mockImplementation(async () => ({
      success: true,
      data: sameProductPage,
      total: 0,
    }))

    const wrapper = mountTab()
    await flushPromises()

    expect(outsourceApi.processTypes).toHaveBeenCalledTimes(20)
    expect(wrapper.findAll('tbody tr')).toHaveLength(1)
    // 极端数据不得一次性渲染成 DOM：首屏最多 50 个 chip，其余显式展开
    expect(wrapper.findAll('.osp-proc-chip')).toHaveLength(50)
    // 护栏截断必须可观测（OCR-3 Low）：静默截断=同一种缺陷换个阈值重现
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining('护栏'))
    warnSpy.mockRestore()
  }, 30_000)

  it('单个产品工序过多时先渲染 50 个，可展开完整列表', async () => {
    const manyProcesses = Array.from({ length: 60 }, (_, i) => ({
      ...genPresets(i + 1, 1, 1)[0]!,
    }))
    vi.mocked(outsourceApi.processTypes).mockResolvedValue(ok(manyProcesses))

    const wrapper = mountTab()
    await flushPromises()

    expect(wrapper.findAll('tbody tr')).toHaveLength(1)
    expect(wrapper.findAll('.osp-proc-chip')).toHaveLength(50)
    const more = wrapper.find('.osp-chip-more')
    expect(more.text()).toContain('+10 道工序')

    await more.trigger('click')
    expect(wrapper.findAll('.osp-proc-chip')).toHaveLength(60)
    expect(wrapper.find('.osp-chip-more').text()).toBe('收起')
  })

  it('后续页失败时保留旧完整缓存，不用不完整新结果覆盖', async () => {
    const oldComplete = genPresets(1000, 600, 1000)
    const newPage1 = genPresets(1, PAGE_SIZE, 1)
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.mocked(outsourceApi.processTypes).mockImplementation(async (params?: { page?: number }) => {
      if (params?.page === 2) throw new Error('network down')
      return { success: true, data: newPage1, total: PAGE_SIZE + 100 }
    })

    const wrapper = mountTab([], { items: oldComplete, partial: 'none' })
    await flushPromises()

    expect(outsourceApi.processTypes).toHaveBeenCalledTimes(2)
    expect(wrapper.findAll('tbody tr')).toHaveLength(600)
    expect(wrapper.find('.osp-partial').exists()).toBe(true)
    warnSpy.mockRestore()
  })
})

describe('OutsourcePresetTab — 分页错误处理与 total 收口（OCR-3 M4/Low）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('M4: 首屏失败显示错误态与重试入口，而非「暂无产品」空态；重试后恢复', async () => {
    const three = genPresets(1, 3, 1)
    vi.mocked(outsourceApi.processTypes)
      .mockRejectedValueOnce(new Error('network down'))
      .mockResolvedValueOnce(ok(three))
    const wrapper = mountTab()
    await flushPromises()

    // 错误态：不是「暂无产品」的误导性空态（当前实现无错误分支 → 落空态，Red）
    expect(wrapper.find('.osp-error').exists()).toBe(true)
    expect(wrapper.find('.osp-empty').text()).not.toContain('暂无产品')

    await wrapper.find('.osp-retry-btn').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('tbody tr')).toHaveLength(3)
  })

  it('M4: 后续页失败保留已取到的数据，不清空整表', async () => {
    const page1 = genPresets(1, PAGE_SIZE, 1)
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.mocked(outsourceApi.processTypes).mockImplementation(async (params?: { page?: number }) => {
      if (params?.page === 2) throw new Error('network down')
      // total > 500：表达「还有更多」，total 收口不会在第 1 页后提前结束
      return { success: true, data: page1, total: PAGE_SIZE + 100 }
    })
    const wrapper = mountTab()
    await flushPromises()

    // 首页 500 条已到手：第 2 页失败不得让整表清空成空态（当前实现 queryFn 整体 reject → 0 行，Red）
    expect(outsourceApi.processTypes).toHaveBeenCalledTimes(2)
    expect(wrapper.findAll('tbody tr')).toHaveLength(500)
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining('第 2 页'))
    // OCR-4 M139：isError 仍 false、重试按钮不会出现，不完整列表必须以 toast 让用户可感知
    expect(toast.warning).toHaveBeenCalledWith('工序预设列表加载不完整，请刷新重试')
    warnSpy.mockRestore()
  })

  it('M4(OCR-4): 拉取失败时搜索选中的待配置产品不得掩盖错误态，必须露出错误+重试', async () => {
    vi.mocked(outsourceApi.processTypes).mockRejectedValue(new Error('network down'))
    const wrapper = mountTab([{ product_id: 9, product_name: '待配置产品', product_barcode: null, factory: null }])
    await flushPromises()

    // 修复前：错误态条件用 productCards（含 pendingProducts）判空 → 非空 → 跳过错误态，
    // 渲染成只有 pending 行的「未配置」表格，拉取失败被静默掩盖（Red）
    expect(wrapper.find('.osp-error').exists()).toBe(true)
    expect(wrapper.find('.osp-retry-btn').exists()).toBe(true)
  })

  it('Low: 记录数恰为页大小整数倍时用 total 收口，不多拉一次空页', async () => {
    const page1 = genPresets(1, PAGE_SIZE, 1)
    vi.mocked(outsourceApi.processTypes).mockImplementation(async (params?: { page?: number }) => ({
      success: true,
      data: params?.page === 1 ? page1 : [],
      total: PAGE_SIZE, // 共 500 条：第 1 页已取完
    }))
    const wrapper = mountTab()
    await flushPromises()

    // 当前实现只看「本页是否满页」→ 满页续拉第 2 次空请求（Red）
    expect(outsourceApi.processTypes).toHaveBeenCalledTimes(1)
    expect(wrapper.findAll('tbody tr')).toHaveLength(500)
  })
})