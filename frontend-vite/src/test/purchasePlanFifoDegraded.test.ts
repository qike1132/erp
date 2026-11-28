import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

// CI（GitHub Actions）磁盘较慢：挂载视图会触发 PurchasePlanView 里两个
// defineAsyncComponent 的动态导入，模块 chunk 在 vitest 环境拆除后才解析完
// → EnvironmentTeardownError 未处理拒绝 → vitest 进程整体退出非 0
// （1609 个用例全过步骤仍红，2026-10-21 CI 实测）。在环境存活期内预热
// 两个对话框的模块缓存，使挂载时的 import() 立即命中缓存。
beforeAll(async () => {
  await Promise.all([
    import('@/views/purchase-plan/components/CreateShipmentPlanDialog.vue'),
    import('@/views/purchase-plan/components/SkuDetailDialog.vue'),
  ])
})

/**
 * 审计 #4：后端生产量分配降级标记（fifo_degraded）必须在采购计划页可见。
 *
 * 降级时后端返回 total_produced / 已生产 / 待生产全为 0，页面把「取不到」
 * 渲染成「一件都没生产」——与真的没生产在像素上无法区分，用户会按假的
 * 生产进度去排产/催单。与 Z02-R6 的库存降级是同一类缺陷，处置也照抄。
 */

const monthlyAggregated = vi.fn()

// 采购计划页按 production_plan_manage 门控「新建/导入/模板」入口，
// 会读 auth store；本用例只验降级横幅，直接给一个有权限的假 store。
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    user: { username: 'tester', permissions: ['production_plan_manage'] },
    hasPermission: (code: string) => code === 'production_plan_manage',
  }),
}))

vi.mock('@/api', () => ({
  planApi: {
    monthlyAggregated: (...args: unknown[]) => monthlyAggregated(...args),
    list: vi.fn(),
    detail: vi.fn(),
    create: vi.fn(),
  },
}))

import PurchasePlanView from '@/views/purchase-plan/PurchasePlanView.vue'

function aggPayload(fifoDegraded: boolean) {
  return {
    year: 2026,
    month: 4,
    days_in_month: 30,
    rows: [{ date: '2026-04-15', dayNum: 15, _dayNum: 15, totalQty: 200, customers: [] }],
    sku_summary: [],
    sku_date_index: {},
    customers: [],
    customer_totals: {},
    fifo_degraded: fifoDegraded,
    inventory_degraded: false,
  }
}

async function mountView(fifoDegraded: boolean) {
  monthlyAggregated.mockResolvedValue(aggPayload(fifoDegraded))
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = mount(PurchasePlanView, {
    global: {
      plugins: [[VueQueryPlugin, { queryClient }]],
      stubs: {
        PurchasePlanHeader: true,
        PurchasePlanBoard: true,
        CreateShipmentPlanDialog: true,
        SkuDetailDialog: true,
      },
    },
  })
  await flushPromises()
  // 弹窗是 defineAsyncComponent：让它的动态 import 在环境销毁前落地，
  // 否则 vitest 记一条 EnvironmentTeardownError（CI 按未处理拒绝判红）
  await new Promise((r) => setTimeout(r, 0))
  return wrapper
}

describe('采购计划页生产进度降级提示（审计 #4）', () => {
  beforeEach(() => monthlyAggregated.mockReset())

  it('fifo_degraded=true 时渲染警示条，并说明 0 不代表没生产', async () => {
    const wrapper = await mountView(true)
    const banner = wrapper.find('.pp-fifo-degraded')
    expect(banner.exists()).toBe(true)
    expect(banner.attributes('role')).toBe('alert')
    // 手写文案关键字：只说「分配失败」而不点明「0 不代表没生产」，
    // 用户照样会把 0 当真值（这正是缺陷本身）
    expect(banner.text()).toContain('不代表真的没生产')
  })

  it('未降级时不得出现该警示条（否则警示条会被当成常态噪音忽略）', async () => {
    const wrapper = await mountView(false)
    expect(wrapper.find('.pp-fifo-degraded').exists()).toBe(false)
  })
})
