/**
 * PurchasePlanHeader —— 出货计划页头部两行（方案B，2026-11-28 owner 拍板合并两 Tab 后重写）。
 *
 * 结构固化两条：
 *   1. 头部只剩工厂 Tab 组一个 Tab 组（视图 Tab 已随两 Tab 合并消失）；
 *   2. 头部内所有交互（翻月 / 导出 / 新建）都只上抛事件，不自作主张。
 */
import { describe, it, expect } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import PurchasePlanHeader from '@/views/purchase-plan/components/PurchasePlanHeader.vue'

const KPI = {
  planQty: 22815,
  planDays: 11,
  custN: 3,
  skuN: 5,
  peakDay: 24,
  peakQty: 1200,
  riskDays: 6,
  riskOverdue: 4,
  riskExpiring: 2,
  riskQty: 8750,
}

function mountHeader(over: Record<string, unknown> = {}): VueWrapper {
  return mount(PurchasePlanHeader, {
    props: {
      y: 2026,
      m: 9,
      factories: ['东莞', '湖北'],
      factoryTotals: { 东莞: 100, 湖北: 50 },
      kpi: KPI,
      factory: '东莞',
      globalKw: '',
      ...over,
    },
    global: {
      stubs: {
        FontAwesomeIcon: { template: '<i />' },
        UiSpinner: { template: '<i />' },
        UiSearchInput: { template: '<input />' },
        UiPagination: { template: '<div />' },
      },
    },
  })
}

describe('PurchasePlanHeader：工厂 Tab 独存', () => {
  it('头部只剩工厂 Tab 组（原视图 Tab 组已随两 Tab 合并消失）', () => {
    const w = mountHeader()
    const groups = w.findAll('.sp-tab-group')
    expect(groups).toHaveLength(1)
    expect(groups[0]?.find("[data-f='东莞']").exists()).toBe(true)
    expect(w.text()).not.toContain('排产日历')
    expect(w.text()).not.toContain('月度汇总')
  })

  it('一行信息条渲染五格（本月计划/客户/SKU/峰值日/风险）', () => {
    const w = mountHeader()
    expect(w.findAll('.sp-kpi')).toHaveLength(5)
    expect(w.text()).toContain('22,815')
    expect(w.text()).toContain('24日')
  })
})

describe('PurchasePlanHeader：交互只上抛', () => {
  it('点月份前后各自上抛 prev/next', async () => {
    const w = mountHeader()
    const btns = w.findAll('.sp-nav-btn')
    await btns[0]?.trigger('click')
    await btns[1]?.trigger('click')
    expect(w.emitted('prev')).toHaveLength(1)
    expect(w.emitted('next')).toHaveLength(1)
  })

  it('点导出/新建上抛 export/create', async () => {
    const w = mountHeader()
    await w.find("[aria-label='导出']").trigger('click')
    await w.find("[aria-label='新建']").trigger('click')
    expect(w.emitted('export')).toHaveLength(1)
    expect(w.emitted('create')).toHaveLength(1)
  })
})
