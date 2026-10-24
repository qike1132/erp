import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

import ProductionTrendPanel from '@/views/production/components/ProductionTrendPanel.vue'
import type { TrendResponse } from '@/types'

// CI flake（2026-10-24 PR#12 两轮实测）：真 echarts 链路在 jsdom 下有两个死法——
// ① 挂载时动态 import 跨越环境拆除（EnvironmentTeardownError: Cannot load
//    echarts/core.js，CI 慢速 FS 竞态）；
// ② 预热后 echarts.init 真跑 zrender，jsdom 无 canvas → Layer.initContext
//    null context → 6 个 unhandled rejection。
// 本测试只断言 DOM 结构（空态/容器/骨架/标题），init 一个 stub 图表即可，
// 彻底脱离真 echarts 导入链与画布实现。
vi.mock('@/utils/echartsPreload', () => ({
  ensureEcharts: async () => ({
    init: () => ({
      isDisposed: () => false,
      dispose: () => undefined,
      setOption: () => undefined,
      resize: () => undefined,
    }),
  }),
}))

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

  it('后台刷新期间图表容器不被销毁（trend 引用不变）', async () => {
    const days = [{ date: '2026-09-01', filling: 5, handcraft: 0, packaging: 0, total: 5 }]
    const t = trend(days)
    const wrapper = mount(ProductionTrendPanel, { props: { trend: t, loading: false } })
    expect(wrapper.find('[data-test="trend-chart"]').exists()).toBe(true)

    await wrapper.setProps({ loading: true })
    expect(wrapper.find('[data-test="trend-chart"]').exists()).toBe(true)

    await wrapper.setProps({ loading: false, trend: t })
    expect(wrapper.find('[data-test="trend-chart"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="trend-skeleton"]').exists()).toBe(false)
  })
})
