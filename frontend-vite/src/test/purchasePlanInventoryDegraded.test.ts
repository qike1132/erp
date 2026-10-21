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
 * Z02-R6：后端库存映射降级标记（inventory_degraded）必须在采购计划页可见。
 *
 * 降级时后端返回的是**空库存映射**，页面把「取不到」渲染成「库存 0 / 全部缺口」，
 * 与「真的没货」在像素上无法区分——用户会按假的缺口去下单。
 */

const monthlyAggregated = vi.fn()

vi.mock('@/api', () => ({
  planApi: {
    monthlyAggregated: (...args: unknown[]) => monthlyAggregated(...args),
    list: vi.fn(),
    detail: vi.fn(),
    create: vi.fn(),
  },
}))

import PurchasePlanView from '@/views/purchase-plan/PurchasePlanView.vue'

function aggPayload(inventoryDegraded: boolean) {
  return {
    year: 2026,
    month: 4,
    days_in_month: 30,
    rows: [{ date: '2026-04-15', dayNum: 15, _dayNum: 15, totalQty: 200, customers: [] }],
    sku_summary: [],
    sku_date_index: {},
    customers: [],
    customer_totals: {},
    fifo_degraded: false,
    inventory_degraded: inventoryDegraded,
  }
}

async function mountView(inventoryDegraded: boolean) {
  monthlyAggregated.mockResolvedValue(aggPayload(inventoryDegraded))
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = mount(PurchasePlanView, {
    global: {
      plugins: [[VueQueryPlugin, { queryClient }]],
      stubs: {
        PurchasePlanHeader: true,
        PurchasePlanDailyTab: true,
        PurchasePlanMonthlySummary: true,
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

describe('采购计划页库存降级提示（Z02-R6）', () => {
  beforeEach(() => monthlyAggregated.mockReset())

  it('inventory_degraded=true 时渲染警示条，并说明 0 不代表没货', async () => {
    const wrapper = await mountView(true)
    const banner = wrapper.find('.pp-degraded')
    expect(banner.exists()).toBe(true)
    expect(banner.attributes('role')).toBe('alert')
    expect(banner.text()).toContain('不可信')
  })

  it('未降级时不得出现警示条（否则警示条会被当成常态噪音忽略）', async () => {
    const wrapper = await mountView(false)
    expect(wrapper.find('.pp-degraded').exists()).toBe(false)
  })
})
