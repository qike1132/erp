/**
 * AUD-20 回归：移动端订单状态筛选必须使用后端中文状态值（2026-10-17 审计）。
 *
 * 缺陷：chips 传 pending/completed 等英文键，/orders/list 按等值匹配返回空列表，
 * 状态筛选 100% 失效；handleSearch 无 catch，失败时用户零感知。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'

const mocks = vi.hoisted(() => ({
  orderApi: { list: vi.fn() },
  showToast: vi.fn(),
}))

vi.mock('@/api', () => ({ orderApi: mocks.orderApi }))
vi.mock('@/composables/useToast', () => ({ showToast: mocks.showToast }))

import MCustomerOrderView from '@/mobile/views/customer-order/MCustomerOrderView.vue'
import MFilterChips from '@/mobile/components/MFilterChips.vue'

const VALID_STATUSES = ['待备货', '部分备货', '已备货', '待出货', '已出货', '批次已完成', '已取消']

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: { template: '<div />' } }],
  })
}

describe('AUD-20 移动端订单状态筛选', () => {
  beforeEach(() => {
    mocks.orderApi.list.mockReset()
    mocks.showToast.mockReset()
    mocks.orderApi.list.mockResolvedValue({ data: [], total: 0 })
  })

  it('chips 值全部来自后端中文状态白名单', async () => {
    const wrapper = mount(MCustomerOrderView, {
      global: { plugins: [makeRouter()] },
    })
    await flushPromises()

    const chips = wrapper.findComponent(MFilterChips).props('chips') as Array<{ value: string }>
    const values = chips.map(c => c.value).filter(v => v !== 'all')

    expect(values.length).toBeGreaterThan(0)
    for (const v of values) expect(VALID_STATUSES).toContain(v)
  })

  it('切换 chip 时请求参数使用中文状态值', async () => {
    const wrapper = mount(MCustomerOrderView, {
      global: { plugins: [makeRouter()] },
    })
    await flushPromises()
    mocks.orderApi.list.mockClear()

    wrapper.findComponent(MFilterChips).vm.$emit('update:modelValue', '已备货')
    await nextTick()
    await flushPromises()

    expect(mocks.orderApi.list).toHaveBeenCalled()
    const params = mocks.orderApi.list.mock.calls.at(-1)?.[0] as { status: string }
    expect(params.status).toBe('已备货')
  })

  it('查询失败时有用户可见提示（不再静默）', async () => {
    mocks.orderApi.list.mockRejectedValue(new Error('network down'))
    mount(MCustomerOrderView, { global: { plugins: [makeRouter()] } })
    await flushPromises()

    expect(mocks.showToast).toHaveBeenCalledWith('订单查询失败，请重试', 'error')
  })
})
