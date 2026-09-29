/**
 * KPI 四格 + 月份导航。
 * 覆盖这次去重复的核心动作：原先把「已延期」「临期≤3天」拆成两格、与右栏风险清单重复播报，
 * 现合并为一格「风险 N 天」——这里断言合并口径与 0 风险时的降级文案。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import PurchasePlanKpiStrip from '@/views/purchase-plan/components/PurchasePlanKpiStrip.vue'
import PurchasePlanMonthNav from '@/views/purchase-plan/components/PurchasePlanMonthNav.vue'

const KPI = {
  planQty: 22815,
  shippedQty: 14065,
  remainQty: 8750,
  pct: 61.6,
  planDays: 11,
  riskDays: 6,
  riskOverdue: 4,
  riskExpiring: 2,
  riskQty: 8750,
}

function mountKpi(over: Partial<typeof KPI> = {}) {
  return mount(PurchasePlanKpiStrip, { props: { ...KPI, ...over } })
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date('2026-09-28T10:00:00'))
})
afterEach(() => { vi.useRealTimers() })

describe('PurchasePlanKpiStrip：四格', () => {
  it('只有四格（原先是六格，已延期/临期两格并入风险）', () => {
    const w = mountKpi()
    expect(w.findAll('.sp-kpi')).toHaveLength(4)
    expect(w.text()).not.toContain('已延期')
    expect(w.text()).not.toContain('临期≤3天')
  })

  it('数量走千分位，几十万位的量级一眼可辨', () => {
    const w = mountKpi()
    expect(w.text()).toContain('22,815')
    expect(w.text()).toContain('14,065')
    expect(w.text()).toContain('61.6%')
  })

  it('风险格给出天数，明细在提示行（逾期/临期/件数）', () => {
    const w = mountKpi()
    const risk = w.findAll('.sp-kpi')[3]
    expect(risk?.text()).toContain('6 天')
    expect(risk?.text()).toContain('逾期 4')
    expect(risk?.text()).toContain('临期 2')
    expect(risk?.text()).toContain('8,750件')
  })

  it('无风险时不显示「0 天」，而是明确说没事', () => {
    const w = mountKpi({ riskDays: 0, riskOverdue: 0, riskExpiring: 0, riskQty: 0 })
    expect(w.findAll('.sp-kpi')[3]?.text()).toContain('本月无逾期与临期')
  })

  it('完成率进度条按阈值换色（0 红 / 未满 100 琥珀 / 满 100 绿）', () => {
    expect(mountKpi({ pct: 0 }).find('.sp-meter > i').classes()).toContain('sp-meter-r')
    expect(mountKpi({ pct: 61.6 }).find('.sp-meter > i').classes()).toContain('sp-meter-a')
    expect(mountKpi({ pct: 100 }).find('.sp-meter > i').classes()).toContain('sp-meter-g')
  })

  it('计划量副标题带排产日天数', () => {
    expect(mountKpi().findAll('.sp-kpi')[0]?.text()).toContain('11 个排产日')
  })
})

describe('PurchasePlanMonthNav', () => {
  it('显示年月，两位补零', () => {
    const w = mount(PurchasePlanMonthNav, { props: { y: 2026, m: 9 }, global: { stubs: { FontAwesomeIcon: { template: '<i />' } } } })
    expect(w.find('.sp-nav-lbl').text()).toBe('2026年09月')
  })

  it('在本月时不显示「回到本月」（省一个常年无用的按钮）', () => {
    const w = mount(PurchasePlanMonthNav, { props: { y: 2026, m: 9 }, global: { stubs: { FontAwesomeIcon: { template: '<i />' } } } })
    expect(w.find('.sp-nav-reset').exists()).toBe(false)
  })

  it('不在本月时给出「回到本月」，点击上抛 reset', async () => {
    const w = mount(PurchasePlanMonthNav, { props: { y: 2026, m: 8 }, global: { stubs: { FontAwesomeIcon: { template: '<i />' } } } })
    await w.find('.sp-nav-reset').trigger('click')
    expect(w.emitted('reset')).toHaveLength(1)
  })

  it('前后翻页各自上抛', async () => {
    const w = mount(PurchasePlanMonthNav, { props: { y: 2026, m: 9 }, global: { stubs: { FontAwesomeIcon: { template: '<i />' } } } })
    const btns = w.findAll('.sp-nav-btn')
    await btns[0]?.trigger('click')
    await btns[1]?.trigger('click')
    expect(w.emitted('prev')).toHaveLength(1)
    expect(w.emitted('next')).toHaveLength(1)
  })
})
