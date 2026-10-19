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
import type { OutsourceProcessType } from '@/api/outsource'
import OutsourcePresetTab from '@/views/outsource/components/OutsourcePresetTab.vue'

/** 与组件内一致的取数口径（断言参数用，勿复制漂移：本测试就是锁它的） */
const PAGE_SIZE = 500

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

function mountTab() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(OutsourcePresetTab, {
    props: { pendingProducts: [] },
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
    vi.mocked(outsourceApi.processTypes).mockImplementation(async (params?: { page?: number }) => {
      return ok(params?.page === 2 ? page2 : page1)
    })

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
    // 20×500=10000 个，jsdom 下成本可观，放宽超时避免环境波动误报
    const sameProductPage = Array.from({ length: PAGE_SIZE }, (_, i) => ({
      ...genPresets(i + 1, 1, 1)[0]!,
    }))
    vi.mocked(outsourceApi.processTypes).mockImplementation(async () => ok(sameProductPage))

    const wrapper = mountTab()
    await flushPromises()

    expect(outsourceApi.processTypes).toHaveBeenCalledTimes(20)
    expect(wrapper.findAll('tbody tr')).toHaveLength(1)
  }, 30_000)
})