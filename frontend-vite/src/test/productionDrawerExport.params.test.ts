import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

/**
 * 回归锁（2026-11-16 上线前审计 H-3）：生产报表**抽屉导出**必须带上「录单人 / 关键词」。
 *
 * 事故形态：后端 `daily_production.export_records` 早已支持 created_by/keyword 两个查询参数，
 * 但前端两个调用点谁都没传 —— 抽屉里按录单人/关键词筛过的列表，导出的 Excel 是**全集**
 * （行数可达屏幕的十几倍），用户拿去对账无法解释。屏幕看到 A、导出得到 B。
 *
 * 拦的是「把这两个键再删掉」：删除后 `dailyProductionApi.export` 收到的参数里没有
 * created_by/keyword，本文件两条断言都会红。
 */
const { exportMock } = vi.hoisted(() => ({ exportMock: vi.fn() }))
exportMock.mockResolvedValue(undefined)

vi.mock('@/api/production', () => ({
  dailyProductionApi: {
    dailySummary: vi.fn().mockResolvedValue({
      date: '2026-09-29', departments: [], overall_quantity: 0, overall_value: 0, overall_sku_count: 0,
    }),
    monthlySummary: vi.fn().mockResolvedValue({
      year: 2026, month: 9, daily_data: [], monthly_departments: [],
      monthly_total_quantity: 0, monthly_total_value: 0,
    }),
    trend: vi.fn().mockResolvedValue({
      success: true, start_date: '2026-09-01', end_date: '2026-09-30', departments: [], days: [],
    }),
    records: vi.fn().mockResolvedValue({
      success: true, data: [], total: 0, page: 1, per_page: 50, pages: 0, stats: null,
    }),
    deleteRecord: vi.fn(),
    export: exportMock,
  },
}))

vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))

import ProductionView from '@/views/production/ProductionView.vue'
import type { RecordFilters } from '@/views/production/composables/recordFilters'

function mountView() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(ProductionView, {
    global: {
      plugins: [[VueQueryPlugin, { queryClient }]],
      stubs: {
        CockpitKpiRow: { template: '<div />' },
        ProductionTrendPanel: { template: '<div />' },
        DeptRankPanel: { template: '<div />' },
        DeptDrillCards: { template: '<div />' },
        // 带 name + emits：用例要替用户点「抽屉里的导出」
        RecordDrawer: { name: 'RecordDrawer', emits: ['export'], template: '<div />' },
        RecordEditDialog: { name: 'RecordEditDialog', template: '<div />' },
        ProductionEntryPanel: { name: 'ProductionEntryPanel', props: ['open', 'selectedDate'], template: '<div />' },
        teleport: true,
      },
    },
  })
}

/** 触发抽屉导出（RecordDrawer 的 export 事件）。 */
async function triggerDrawerExport(wrapper: ReturnType<typeof mountView>) {
  wrapper.findComponent({ name: 'RecordDrawer' }).vm.$emit('export')
  await flushPromises()
}

/** 本次导出实际收到的参数（断言只发生一次调用）。 */
function exportedParams(): Record<string, unknown> {
  expect(capturedCalls).toHaveLength(1)
  return capturedCalls[0] as Record<string, unknown>
}

const capturedCalls: Record<string, unknown>[] = []

beforeEach(() => {
  capturedCalls.length = 0
  exportMock.mockClear()
  exportMock.mockImplementation((params?: unknown) => {
    capturedCalls.push((params ?? {}) as Record<string, unknown>)
    return Promise.resolve(undefined)
  })
})

describe('生产报表抽屉导出的参数（H-3）', () => {
  it('筛了录单人 + 关键词时，导出必须把两个键带上', async () => {
    const wrapper = mountView()
    const vm = wrapper.vm as unknown as { recordsFilters: RecordFilters }
    vm.recordsFilters = { ...vm.recordsFilters, createdBy: '张三', keyword: '企鹅' }

    await triggerDrawerExport(wrapper)

    const params = exportedParams()
    expect(params).toMatchObject({ created_by: '张三', keyword: '企鹅' })
    // 日期区间仍必须带上（折算基准是 selectedDate，不是「今天」）
    expect(params.start_date).toBeTruthy()
    expect(params.end_date).toBeTruthy()
  })

  it('未筛选时两键为 undefined（不能把空串发下去，后端默认值才生效）', async () => {
    const wrapper = mountView()
    await triggerDrawerExport(wrapper)

    const params = exportedParams()
    expect(params.created_by).toBeUndefined()
    expect(params.keyword).toBeUndefined()
  })

  it('只筛关键词时不得污染录单人键（两键各自独立）', async () => {
    const wrapper = mountView()
    const vm = wrapper.vm as unknown as { recordsFilters: RecordFilters }
    vm.recordsFilters = { ...vm.recordsFilters, keyword: '69码' }

    await triggerDrawerExport(wrapper)

    const params = exportedParams()
    expect(params.keyword).toBe('69码')
    expect(params.created_by).toBeUndefined()
  })
})
