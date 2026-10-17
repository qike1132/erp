/**
 * AUD-21/22 回归：移动端列表必须服务端分页、库存状态筛选下推服务端
 * （2026-10-17 审计）。
 *
 * 缺陷：采购「已完成/待生成」tab 无分页；库存/产品/批次/皮套固定第 1 页；
 * 库存「零库存/在库」只过滤截断后的首页数据。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'

const mocks = vi.hoisted(() => ({
  productApi: { list: vi.fn() },
  stockApi: { inventory: vi.fn() },
  purchaseApi: {
    orders: vi.fn(),
    unprocessedOrders: vi.fn(),
    completed: vi.fn(),
    oneClickGenerate: vi.fn(),
  },
  caseApi: { inventory: vi.fn(), search: vi.fn(), movement: vi.fn() },
}))

vi.mock('@/api', () => mocks)
vi.mock('@/api/case', () => ({ caseApi: mocks.caseApi }))

import MPurchaseView from '@/mobile/views/purchase/MPurchaseView.vue'
import MStockView from '@/mobile/views/stock/MStockView.vue'
import MProductView from '@/mobile/views/product/MProductView.vue'

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: { template: '<div />' } }],
  })
}

const opts = () => ({ global: { plugins: [makeRouter()] } })

describe('AUD-21 采购中心分页', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.purchaseApi.orders.mockResolvedValue({ orders: [], total: 120, pages: 3, current_page: 1 })
    mocks.purchaseApi.unprocessedOrders.mockResolvedValue({ orders: [], total: 120, pages: 3, current_page: 1 })
    mocks.purchaseApi.completed.mockResolvedValue({ orders: [], total: 120, pages: 3, current_page: 1 })
  })

  it('待生成/已完成 tab 翻页时携带对应页码', async () => {
    const wrapper = mount(MPurchaseView, opts())
    await flushPromises()
    const vm = wrapper.vm as unknown as {
      loadUnprocessed: (p: number) => Promise<void>
      loadCompleted: (p: number) => Promise<void>
    }

    await vm.loadUnprocessed(2)
    expect(mocks.purchaseApi.unprocessedOrders).toHaveBeenLastCalledWith({ page: 2, per_page: 50 })

    await vm.loadCompleted(3)
    expect(mocks.purchaseApi.completed).toHaveBeenLastCalledWith({ page: 3, per_page: 50, keyword: '' })
  })
})

describe('AUD-22 库存状态筛选与分页', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.stockApi.inventory.mockResolvedValue({ data: [], total_items: 0 })
    mocks.productApi.list.mockResolvedValue({ items: [], total: 0 })
  })

  it('库存 tab 切换把 stock_status 下推服务端', async () => {
    const wrapper = mount(MStockView, opts())
    await flushPromises()
    const vm = wrapper.vm as unknown as { selectedTab: string }
    vm.selectedTab = 'zero'
    await flushPromises()

    expect(mocks.stockApi.inventory).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 1, stock_status: 'zero' }),
    )
  })

  it('产品列表使用当前页码', async () => {
    const wrapper = mount(MProductView, opts())
    await flushPromises()
    const vm = wrapper.vm as unknown as { page: number; loadProducts: () => Promise<void> }
    vm.page = 2
    await vm.loadProducts()

    expect(mocks.productApi.list).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 2, per_page: 200 }),
    )
  })
})
