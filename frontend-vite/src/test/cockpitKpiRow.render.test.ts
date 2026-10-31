import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import CockpitKpiRow from '@/views/production/components/CockpitKpiRow.vue'
import type { DailySummary, MonthlySummary } from '@/types'

function daily(quantity: number, value: number): DailySummary {
  return {
    date: '2026-09-29',
    departments: [],
    overall_quantity: quantity,
    overall_value: value,
    overall_sku_count: 3,
  }
}

const monthly: MonthlySummary = {
  year: 2026,
  month: 9,
  daily_data: [
    {
      date: '2026-09-01', day: 1,
      filling: { quantity: 10, value: 70, sku_count: 1 },
      handcraft: { quantity: 0, value: 0, sku_count: 0 },
      packaging: { quantity: 0, value: 0, sku_count: 0 },
      total: { quantity: 10, value: 70, sku_count: 1 },
    },
  ],
  monthly_departments: [],
  monthly_total_quantity: 10,
  monthly_total_value: 70,
}

describe('CockpitKpiRow', () => {
  it('渲染四个 KPI：今日产量/今日产值/本月累计/日均产量', () => {
    const wrapper = mount(CockpitKpiRow, {
      props: { today: daily(4250, 27170), yesterday: daily(3780, 25130), monthly, previousMonth: null },
    })

    const text = wrapper.text()
    expect(text).toContain('今日产量')
    expect(text).toContain('今日产值')
    expect(text).toContain('本月累计')
    expect(text).toContain('日均产量')
    expect(text).toContain('4,250')
  })

  it('昨日为 0 时较昨日显示破折号', () => {
    // Review Focus #2 的渲染侧断言：纯函数已测，这里确认界面真的用了它
    const wrapper = mount(CockpitKpiRow, {
      props: { today: daily(100, 700), yesterday: daily(0, 0), monthly, previousMonth: null },
    })

    expect(wrapper.text()).toContain('—')
    expect(wrapper.text()).not.toContain('Infinity')
    expect(wrapper.text()).not.toContain('NaN')
  })

  it('数据未加载时显示骨架而不显示 0', () => {
    const wrapper = mount(CockpitKpiRow, {
      props: { today: null, yesterday: null, monthly: null, previousMonth: null },
    })

    expect(wrapper.find('[data-test="kpi-skeleton"]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('0 件')
  })

  it('本月无生产日时日均显示 0 而非 NaN', () => {
    const emptyMonth: MonthlySummary = {
      ...monthly,
      daily_data: [],
      monthly_total_quantity: 0,
      monthly_total_value: 0,
    }
    const wrapper = mount(CockpitKpiRow, {
      props: { today: daily(0, 0), yesterday: daily(0, 0), monthly: emptyMonth, previousMonth: null },
    })

    expect(wrapper.text()).not.toContain('NaN')
  })

  it('上月无生产日时"较上月"显示破折号', () => {
    // 规格 §4.1 的日均口径含"较上月"；上月无数据时同样是分母为 0 的情形
    const wrapper = mount(CockpitKpiRow, {
      props: { today: daily(100, 700), yesterday: daily(100, 700), monthly, previousMonth: null },
    })

    expect(wrapper.text()).toContain('较上月 —')
  })

  // 2026-10-30 审计 A-M33：没有数据时不能一律当成「还在加载」
  it('请求失败且无数据 → 显示失败态与重试，而不是永远转圈的骨架屏', async () => {
    const wrapper = mount(CockpitKpiRow, {
      props: { today: null, yesterday: null, monthly: null, previousMonth: null, loadFailed: true },
    })

    expect(wrapper.find('[data-test="kpi-error"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="kpi-skeleton"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('汇总数据加载失败')

    await wrapper.find('[data-test="kpi-error"] button').trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
  })

  it('没失败时仍走骨架（loadFailed 缺省不改变原有行为）', () => {
    const wrapper = mount(CockpitKpiRow, {
      props: { today: null, yesterday: null, monthly: null, previousMonth: null },
    })

    expect(wrapper.find('[data-test="kpi-skeleton"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="kpi-error"]').exists()).toBe(false)
  })
})
