/**
 * PurchasePlanHeader —— 采购计划页头部两行。
 *
 * 本任务把 PurchasePlanView.vue 的 .sp-head 抽成本组件，并顺势把工厂 Tab
 * 放到第一行左侧（视图 Tab 在其右）。这里固化两条结构诉求：
 *   1. 工厂 Tab 组（含 data-f='all'）在视图 Tab 组之左；
 *   2. 头部内所有交互（视图切换 / 翻月 / 导出 / 新建）都只上抛事件，不自作主张。
 */
import { describe, it, expect } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import PurchasePlanHeader from '@/views/purchase-plan/components/PurchasePlanHeader.vue'

const KPI = {
  planQty: 22815,
  producedQty: 14065,
  remainQty: 8750,
  pct: 61.6,
  planDays: 11,
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
      viewTab: 'daily',
      factory: 'all',
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

describe('PurchasePlanHeader：工厂 Tab 左置', () => {
  it('工厂 Tab 在视图 Tab 左侧', () => {
    const w = mountHeader()
    const groups = w.findAll('.sp-tab-group')
    expect(groups).toHaveLength(2)
    // 第 0 组是工厂 Tab 组：含 data-f='all'
    expect(groups[0]?.find("[data-f='all']").exists()).toBe(true)
    // 第 1 组是视图 Tab：排产日历 / 月度汇总
    expect(groups[1]?.text()).toContain('排产日历')
    expect(groups[1]?.text()).toContain('月度汇总')
  })
})

describe('PurchasePlanHeader：交互只上抛', () => {
  it('点「月度汇总」上抛 update:viewTab', async () => {
    const w = mountHeader()
    const tab = w.findAll('.sp-tab').find(t => t.text() === '月度汇总')
    await tab?.trigger('click')
    expect(w.emitted('update:viewTab')?.[0]).toEqual(['summary'])
  })

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
