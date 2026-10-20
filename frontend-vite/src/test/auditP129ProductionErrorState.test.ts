/**
 * P1-29 回归：生产报表移动端接口失败静默空白、快速切日期/月份旧响应覆盖新数据。
 *
 * 修复后：catch 置 loadError（403 显示无查看权限），模板渲染错误态 + 重试按钮；
 * daily/monthly 各自请求序号丢弃过期响应。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'

const mocks = vi.hoisted(() => ({
  dailyProductionApi: { dailySummary: vi.fn(), monthlySummary: vi.fn() },
}))

vi.mock('@/api', () => mocks)

import MProductionView from '@/mobile/views/production/MProductionView.vue'
import type { DailySummary, MonthlySummary } from '@/types'

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: { template: '<div />' } }],
  })
}

const opts = () => ({ global: { plugins: [makeRouter()] } })

function dailySummary(deptLabel: string, quantity: number): DailySummary {
  return {
    date: '2026-10-18',
    departments: [
      { department: 'filling', department_label: deptLabel, total_quantity: quantity, total_value: quantity * 10, sku_count: 1 },
    ],
    overall_quantity: quantity,
    overall_value: quantity * 10,
    overall_sku_count: 1,
  }
}

function monthlySummary(quantity: number): MonthlySummary {
  return {
    year: 2026,
    month: 10,
    daily_data: [],
    monthly_departments: [
      { department: 'packaging', department_label: '包装部', total_quantity: quantity, total_value: quantity * 10, sku_count: 1 },
    ],
    monthly_total_quantity: quantity,
    monthly_total_value: quantity * 10,
  }
}

function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((res) => { resolve = res })
  return { promise, resolve }
}

describe('P1-29 生产报表错误态与过期响应', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.dailyProductionApi.dailySummary.mockResolvedValue(dailySummary('充棉部', 100))
    mocks.dailyProductionApi.monthlySummary.mockResolvedValue(monthlySummary(50))
  })

  it('日报失败渲染错误态，重试可再次请求并恢复', async () => {
    mocks.dailyProductionApi.dailySummary
      .mockRejectedValueOnce({ response: { status: 500 } })
      .mockResolvedValueOnce(dailySummary('充棉部', 100))

    const wrapper = mount(MProductionView, opts())
    await flushPromises()
    expect(wrapper.text()).toContain('日报加载失败，请点击重试')

    const retry = wrapper.find('.m-retry-btn')
    expect(retry.exists()).toBe(true)
    await retry.trigger('click')
    await flushPromises()

    expect(mocks.dailyProductionApi.dailySummary).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('充棉部')
    expect(wrapper.text()).not.toContain('日报加载失败')
  })

  it('月报失败渲染错误态（403 显示无查看权限）', async () => {
    mocks.dailyProductionApi.monthlySummary.mockRejectedValueOnce({ response: { status: 403 } })
    const wrapper = mount(MProductionView, opts())
    await flushPromises()

    const vm = wrapper.vm as unknown as { viewTab: string }
    vm.viewTab = 'monthly'
    await flushPromises()

    expect(wrapper.text()).toContain('无查看权限')
    expect(wrapper.find('.m-retry-btn').exists()).toBe(true)
  })

  it('快速切日期时旧响应晚到不覆盖新数据', async () => {
    const first = deferred<DailySummary>()
    const second = deferred<DailySummary>()
    mocks.dailyProductionApi.dailySummary
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise)

    const wrapper = mount(MProductionView, opts())
    await flushPromises()
    await wrapper.find('button[aria-label="下一页"]').trigger('click')
    await flushPromises()

    second.resolve(dailySummary('包装部', 200))
    await flushPromises()
    expect(wrapper.text()).toContain('包装部')

    first.resolve(dailySummary('充棉部', 100))
    await flushPromises()
    expect(wrapper.text()).not.toContain('充棉部')
    expect(wrapper.text()).toContain('包装部')
  })
})
