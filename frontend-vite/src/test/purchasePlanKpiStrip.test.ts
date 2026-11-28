/**
 * 一行信息条（方案B，2026-11-28 owner 拍板）+ 月份导航。
 * 原四格大数字 KPI（含完成率进度条）换成约 40px 单行五格：
 * 本月计划 / 客户 / SKU / 峰值日 / 风险 —— 全部数量口径；
 * 已生产/待生产/进度在下方 SKU 月度统计表按行给，不再在条上重复。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import PurchasePlanKpiStrip from '@/views/purchase-plan/components/PurchasePlanKpiStrip.vue'
import PurchasePlanMonthNav from '@/views/purchase-plan/components/PurchasePlanMonthNav.vue'

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

function mountKpi(over: Partial<typeof KPI> = {}) {
  return mount(PurchasePlanKpiStrip, { props: { ...KPI, ...over } })
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date('2026-09-28T10:00:00'))
})
afterEach(() => { vi.useRealTimers() })

describe('PurchasePlanKpiStrip：一行五格', () => {
  it('只有五格，且不再出现完成率进度条', () => {
    const w = mountKpi()
    expect(w.findAll('.sp-kpi')).toHaveLength(5)
    expect(w.find('.sp-meter').exists()).toBe(false)
    expect(w.text()).not.toContain('已延期')
    expect(w.text()).not.toContain('临期≤3天')
  })

  it('数量走千分位，几十万位的量级一眼可辨；计划格带排产日天数', () => {
    const w = mountKpi()
    expect(w.text()).toContain('22,815')
    expect(w.text()).toContain('11 个排产日')
    expect(w.findAll('.sp-kpi')[1]?.text()).toContain('3')
    expect(w.findAll('.sp-kpi')[2]?.text()).toContain('5')
  })

  it('峰值日格给出日号与当日总量', () => {
    const w = mountKpi()
    const peak = w.findAll('.sp-kpi')[3]
    expect(peak?.text()).toContain('24日')
    expect(peak?.text()).toContain('1,200')
  })

  it('无排产数据时峰值日降级为「—」，不显示假 0', () => {
    const w = mountKpi({ peakDay: 0, peakQty: 0 })
    expect(w.findAll('.sp-kpi')[3]?.text()).toContain('—')
    expect(w.findAll('.sp-kpi')[3]?.text()).not.toContain('件')
  })

  it('风险格给出天数，明细在提示行（逾期/临期/件数）', () => {
    const w = mountKpi()
    const risk = w.findAll('.sp-kpi')[4]
    expect(risk?.text()).toContain('6 天')
    expect(risk?.text()).toContain('逾期 4')
    expect(risk?.text()).toContain('临期 2')
    expect(risk?.text()).toContain('8,750件')
  })

  it('无风险时不显示「0 天」，而是明确说没事', () => {
    const w = mountKpi({ riskDays: 0, riskOverdue: 0, riskExpiring: 0, riskQty: 0 })
    expect(w.findAll('.sp-kpi')[4]?.text()).toContain('本月无逾期与临期')
  })
})

describe('PurchasePlanMonthNav', () => {
  it('显示年月，两位补零', () => {
    const w = mount(PurchasePlanMonthNav, { props: { y: 2026, m: 9 }, global: { stubs: { FontAwesomeIcon: { template: '<i />' } } } })
    expect(w.find('.sp-nav-lbl').text()).toBe('2026年09月')
  })

  it('不再提供「回到本月」按钮（2026-11-01 按需求移除，只保留前后翻页）', () => {
    const w = mount(PurchasePlanMonthNav, { props: { y: 2026, m: 8 }, global: { stubs: { FontAwesomeIcon: { template: '<i />' } } } })
    expect(w.find('.sp-nav-reset').exists()).toBe(false)
    expect(w.text()).not.toContain('回到本月')
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
