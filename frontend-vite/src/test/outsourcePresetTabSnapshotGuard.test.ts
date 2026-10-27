/**
 * OutsourcePresetTab 旧缓存快照防御回归（OCR-4 H1）。
 *
 * 缺陷：queryKey ['outsource-process-types'] 的旧缓存快照是分页信封
 * { success, data, total } 形态（P1-23 分页改造之前 queryFn 的返回形态），
 * 被 persistQueryClient 持久化到 sessionStorage，而 buster 仍是
 * 'binfa-erp-v1' 未升级（main.ts:87）——已打开的页面部署后 F5 会恢复旧
 * 快照，listData.value 是对象而非数组，presets 不可迭代 → byProduct 的
 * for...of 在渲染期抛 TypeError → 预设页整页空白（后台 refetch 来不及救）。
 *
 * 修复：presets 以 Array.isArray 守卫，非数组快照按空数据处理，等待后台
 * refetch 替换为新的裸数组形态。
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

/**
 * 模拟 persistQueryClient 恢复旧快照：挂载前把信封形态写入 queryClient
 * 缓存（setQueryData 与恢复快照对 data/dataUpdatedAt 的效果一致）。
 * 组件 staleTime=15s，快照 fresh → 挂载不触发后台 refetch，data 即快照。
 */
function mountWithSnapshot(snapshot: unknown) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(['outsource-process-types'], snapshot)
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
  // 新实现挂载即重取：旧信封快照不被采用，后台请求返回真实空列表后进入空态。
  vi.mocked(outsourceApi.processTypes).mockResolvedValue({ success: true, data: [], total: 0 })
})

describe('OutsourcePresetTab — 旧缓存信封快照防御（OCR-4 H1）', () => {
  it('恢复分页信封形态的旧快照时组件不炸：按空数据渲染，不迭代对象', async () => {
    // P1-23 之前的快照形态：{ success, data, total } 信封（带真实条目，旧代码会直接迭代对象）
    const three = genPresets(1, 3, 1)
    const wrapper = mountWithSnapshot({ success: true, data: three, total: 3 })
    await flushPromises()

    // 守卫生效：对象快照不进入 byProduct → 0 行、落「暂无产品」空态。
    // 渲染完成本身即证明 for...of 没有对信封对象抛 TypeError（旧代码此处白屏）。
    expect(wrapper.findAll('tbody tr')).toHaveLength(0)
    expect(wrapper.find('.osp-empty').exists()).toBe(true)
    expect(wrapper.find('.osp-empty').text()).toContain('暂无产品')
  })
})