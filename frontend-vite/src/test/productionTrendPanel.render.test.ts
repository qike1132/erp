import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import ProductionTrendPanel from '@/views/production/components/ProductionTrendPanel.vue'
import type { TrendResponse } from '@/types'

function trend(days: TrendResponse['days'], departments = ['filling', 'handcraft', 'packaging']): TrendResponse {
  return { success: true, start_date: '2026-09-01', end_date: '2026-09-30', departments, days }
}

describe('ProductionTrendPanel', () => {
  it('全部为 0 时渲染空态而不是空白画布', () => {
    // Review Focus #3：新上线或该用户范围内无数据时，30 天全是 0
    const zeroDays = Array.from({ length: 30 }, (_, i) => ({
      date: `2026-09-${String(i + 1).padStart(2, '0')}`,
      filling: 0, handcraft: 0, packaging: 0, total: 0,
    }))

    const wrapper = mount(ProductionTrendPanel, { props: { trend: trend(zeroDays), loading: false } })

    expect(wrapper.find('[data-test="trend-empty"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="trend-chart"]').exists()).toBe(false)
  })

  it('有数据时渲染图表容器', () => {
    const days = [{ date: '2026-09-01', filling: 5, handcraft: 0, packaging: 0, total: 5 }]

    const wrapper = mount(ProductionTrendPanel, { props: { trend: trend(days), loading: false } })

    expect(wrapper.find('[data-test="trend-chart"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="trend-empty"]').exists()).toBe(false)
  })

  it('加载中显示骨架', () => {
    const wrapper = mount(ProductionTrendPanel, { props: { trend: null, loading: true } })

    expect(wrapper.find('[data-test="trend-skeleton"]').exists()).toBe(true)
  })

  it('trend 为 null 且不在加载中时渲染空态', () => {
    const wrapper = mount(ProductionTrendPanel, { props: { trend: null, loading: false } })

    expect(wrapper.find('[data-test="trend-empty"]').exists()).toBe(true)
  })

  it('面板标题写明统计区间', () => {
    const days = [{ date: '2026-09-01', filling: 5, handcraft: 0, packaging: 0, total: 5 }]
    const wrapper = mount(ProductionTrendPanel, { props: { trend: trend(days), loading: false } })

    expect(wrapper.text()).toContain('2026-09-01')
    expect(wrapper.text()).toContain('2026-09-30')
  })
})
