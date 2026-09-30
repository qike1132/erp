import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

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
  },
}))

vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))

import ProductionView from '@/views/production/ProductionView.vue'

/**
 * 本测试只验**编排**：四个区块是否就位、下钻是否真的驱动抽屉。
 * 因此把四个区块组件与两个弹窗都 stub 掉 —— 它们是 PrimeVue 重组件
 * （Drawer / DataTable / DatePicker），真挂载需要完整插件，且与本测试的断言无关；
 * 它们各自的渲染由前面任务自己的测试覆盖。
 * 注意：必须提供 QueryClient —— ProductionView 用了 @tanstack/vue-query。
 */
function mountView() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(ProductionView, {
    global: {
      plugins: [[VueQueryPlugin, { queryClient }]],
      stubs: {
        CockpitKpiRow: { template: '<div data-test="cockpit-kpi" />' },
        ProductionTrendPanel: { template: '<div data-test="cockpit-trend" />' },
        DeptRankPanel: { template: '<div data-test="cockpit-rank" />' },
        DeptDrillCards: { template: '<div data-test="cockpit-dept-cards" />' },
        RecordDrawer: { template: '<div data-test="record-drawer" />' },
        RecordEditDialog: { template: '<div />' },
        // 录入弹窗的 stub 带 name 与 open prop：快捷键用例要能读到它是否被打开。
        ProductionEntryDialog: { name: 'ProductionEntryDialog', props: ['open', 'selectedDate'], template: '<div />' },
        teleport: true,
      },
    },
  })
}

describe('ProductionView（驾驶舱编排）', () => {
  it('渲染四个区块：KPI 条、趋势面板、部门排行、部门下钻卡', () => {
    const wrapper = mountView()

    expect(wrapper.find('[data-test="cockpit-kpi"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="cockpit-trend"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="cockpit-rank"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="cockpit-dept-cards"]').exists()).toBe(true)
  })

  it('不再渲染日报/月报 Tab', () => {
    const wrapper = mountView()

    expect(wrapper.text()).not.toContain('月报')
  })

  it('工具栏有明细入口与录入入口', () => {
    const wrapper = mountView()

    expect(wrapper.find('[data-test="open-records"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="open-entry"]').exists()).toBe(true)
  })

  it('点部门卡会打开抽屉并预置该部门筛选', async () => {
    const wrapper = mountView()

    // 部门卡在数据加载后才有内容；这里直接调用编排层暴露的 drill 处理
    await (wrapper.vm as unknown as { openRecordsFor: (d: string) => void }).openRecordsFor('filling')

    expect((wrapper.vm as unknown as { recordsOpen: boolean }).recordsOpen).toBe(true)
    expect((wrapper.vm as unknown as { recordsFilters: { department: string } }).recordsFilters.department).toBe('filling')
  })

  it('Ctrl+N 打开录入弹窗', async () => {
    const wrapper = mountView()
    expect((wrapper.vm as unknown as { entryOpen?: boolean }).entryOpen ?? false).toBe(false)

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'n', ctrlKey: true }))
    await nextTick()

    expect(wrapper.findComponent({ name: 'ProductionEntryDialog' }).props('open')).toBe(true)
  })
})
