/**
 * P1-28 回归：出货计划移动端快速切月时，旧月份响应后到会覆盖新月数据。
 *
 * 修复后：loadData 带请求序号，success/catch/finally 三处均校验 seq。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'

const mocks = vi.hoisted(() => ({
  planApi: { monthly: vi.fn() },
}))

vi.mock('@/api', () => ({ planApi: mocks.planApi }))

import MShipmentView from '@/mobile/views/shipment/MShipmentView.vue'
import type { Plan } from '@/views/purchase-plan/components/types'

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: { template: '<div />' } }],
  })
}

const opts = () => ({ global: { plugins: [makeRouter()] } })

function plan(detailId: number, customer: string, planDate: string): Plan {
  return {
    detail_id: detailId,
    plan_id: detailId,
    customer_name: customer,
    product_name: '毛绒玩具',
    barcode: `P${detailId}`,
    quantity: 10,
    produced_qty: 0,
    remaining_qty: 10,
    plan_date: planDate,
  }
}

function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((res) => { resolve = res })
  return { promise, resolve }
}

describe('P1-28 出货计划切月请求序号', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // jsdom 未实现 scrollIntoView；组件在选中日期变化后会滚动定位
    Element.prototype.scrollIntoView = vi.fn()
  })

  it('快速切月时旧响应晚到不覆盖新月数据', async () => {
    const requests: Array<ReturnType<typeof deferred<Record<string, unknown>>>> = []
    mocks.planApi.monthly.mockImplementation(() => {
      const req = deferred<Record<string, unknown>>()
      requests.push(req)
      return req.promise
    })

    const wrapper = mount(MShipmentView, opts())
    await flushPromises()
    // 首屏（当前月）先返回空数据
    requests[0]!.resolve({ plans_by_date: {} })
    await flushPromises()

    // 连点两次下一月：11 月请求（旧）与 12 月请求（新）都在途
    await wrapper.find('button[aria-label="下一月"]').trigger('click')
    await wrapper.find('button[aria-label="下一月"]').trigger('click')
    expect(requests).toHaveLength(3)

    // 12 月先返回并渲染
    requests[2]!.resolve({ plans_by_date: { '2026-12-01': [plan(2, '新月份客户', '2026-12-01')] } })
    await flushPromises()
    expect(wrapper.text()).toContain('新月份客户')

    // 11 月旧响应后到：必须被丢弃
    requests[1]!.resolve({ plans_by_date: { '2026-11-01': [plan(1, '旧月份客户', '2026-11-01')] } })
    await flushPromises()
    expect(wrapper.text()).not.toContain('旧月份客户')
    expect(wrapper.text()).toContain('新月份客户')
  })

  it('加载失败文案不再承诺「下拉重试」（本页无下拉刷新，P2-7）', async () => {
    mocks.planApi.monthly.mockRejectedValue({ response: { status: 500 } })
    const wrapper = mount(MShipmentView, opts())
    await flushPromises()

    expect(wrapper.text()).toContain('加载失败，请稍后重试')
    expect(wrapper.text()).not.toContain('下拉重试')
  })
})
