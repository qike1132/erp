import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createRouter, createMemoryHistory, type Router } from 'vue-router'

import type {
  DailySummary,
  InventoryItem,
  MonthlySummary,
  Product,
  PurchaseOrder,
  UnprocessedOrder,
} from '@/types'
import { MOBILE_LIST_PAGE_SIZE, MOBILE_PAGE_SIZE } from '@/mobile/constants'

/**
 * S12 移动端数据层统一回归测试。
 *
 * 移动端 4 个列表视图原先各自声明了后端 DTO 的副本（Product / StockItem /
 * PurchaseOrderItem / ProductionSummary）并做字段重映射，副本会与后端悄悄漂移：
 * - MStockView 自建的 safety_stock 后端根本不返回（恒为 0），「低库存」筛选恒为假；
 * - MPurchaseView 的 created_at 在 DTO 里叫 create_time，详情页永远显示「—」；
 * - MProductionView 的 ProductionSummary 带索引签名，掩盖了日报/月报字段差异。
 * 本文件锁定「直接用 @/types 的 DTO 字段渲染」这一契约。
 */

const mocks = vi.hoisted(() => ({
  productApi: { list: vi.fn() },
  stockApi: { inventory: vi.fn() },
  purchaseApi: {
    orders: vi.fn(),
    unprocessedOrders: vi.fn(),
    completed: vi.fn(),
    oneClickGenerate: vi.fn(),
  },
  dailyProductionApi: { dailySummary: vi.fn(), monthlySummary: vi.fn() },
}))

vi.mock('@/api', () => mocks)

import MProductView from '@/mobile/views/product/MProductView.vue'
import MStockView from '@/mobile/views/stock/MStockView.vue'
import MPurchaseView from '@/mobile/views/purchase/MPurchaseView.vue'
import MProductionView from '@/mobile/views/production/MProductionView.vue'

function makeRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: { template: '<div />' } }],
  })
}

function product(over: Partial<Product> = {}): Product {
  return { id: 1, name: '招财猫挂件', barcode: 'P001', specification: '20cm', status: true, ...over }
}

function inventoryItem(over: Partial<InventoryItem> = {}): InventoryItem {
  return {
    product_id: 7,
    product_name: 'PP棉',
    barcode: 'M01',
    current_stock: 120,
    total_stockin: 200,
    total_stockout: 80,
    total_deducted: 0,
    ...over,
  }
}

function inventoryResponse(data: InventoryItem[]) {
  return {
    success: true,
    data,
    total_order_quantity: 0,
    total_stockin_quantity: 0,
    total_stock: 0,
    total_available_stock: 0,
    all_customers: [],
    total_items: data.length,
    page: 1,
    per_page: MOBILE_LIST_PAGE_SIZE,
  }
}

function purchaseOrder(over: Partial<PurchaseOrder> = {}): PurchaseOrder {
  return {
    id: 5,
    order_no: 'PO20260901001',
    status: 'pending',
    customer_name: '客户A',
    supplier_name: '供应商B',
    create_time: '2026-09-01 10:00:00',
    order_date: '2026-09-01',
    product_name: '招财猫挂件',
    quantity: 100,
    ...over,
  }
}

function unprocessedOrder(over: Partial<UnprocessedOrder> = {}): UnprocessedOrder {
  return {
    id: 9,
    composite_id: 'order:9',
    order_no: 'PO20260902001',
    customer: '客户C',
    product_name: '泰迪熊',
    quantity: 20,
    order_date: '2026-09-02',
    status: 'pending',
    ...over,
  }
}

function dailySummary(over: Partial<DailySummary> = {}): DailySummary {
  return {
    date: '2026-09-30',
    departments: [
      { department: 'filling', department_label: '充棉部', total_quantity: 100, total_value: 1000, sku_count: 2 },
    ],
    overall_quantity: 100,
    overall_value: 1000,
    overall_sku_count: 2,
    ...over,
  }
}

function monthlySummary(over: Partial<MonthlySummary> = {}): MonthlySummary {
  return {
    year: 2026,
    month: 9,
    daily_data: [],
    monthly_departments: [
      { department: 'packaging', department_label: '包装部', total_quantity: 50, total_value: 500, sku_count: 1 },
    ],
    monthly_total_quantity: 50,
    monthly_total_value: 500,
    ...over,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('S12 移动端数据层统一', () => {
  describe('MProductView（复用 @/types 的 Product）', () => {
    it('直接用 Product 字段渲染，不再把 barcode/name/specification 重映射成 product_code/product_name/spec', async () => {
      mocks.productApi.list.mockResolvedValue({
        items: [
          product(),
          product({ id: 2, name: '泰迪熊', barcode: 'P002', specification: undefined, status: false }),
          product({ id: 3, name: '无码产品', barcode: undefined, specification: undefined }),
        ],
        total: 3,
      })

      const wrapper = mount(MProductView)
      await flushPromises()

      expect(mocks.productApi.list).toHaveBeenCalledWith({ page: 1, per_page: MOBILE_LIST_PAGE_SIZE })
      const text = wrapper.text()
      expect(text).toContain('P001')
      expect(text).toContain('招财猫挂件')
      expect(text).toContain('20cm')
      expect(text).toContain('在产')
      // status === false → 停产；status 缺失（无码产品未传）按在产处理，与旧映射口径一致
      expect(text).toContain('停产')
      // barcode 缺失时展示占位符，而不是渲染 undefined
      expect(text).not.toContain('undefined')
    })

    it('本地搜索按 DTO 字段（barcode / name / specification）过滤', async () => {
      mocks.productApi.list.mockResolvedValue({
        items: [product(), product({ id: 2, name: '泰迪熊', barcode: 'P002', specification: '25cm' })],
        total: 2,
      })

      const wrapper = mount(MProductView)
      await flushPromises()

      const vm = wrapper.vm as unknown as { searchQuery: string }
      vm.searchQuery = '泰迪'
      await nextTick()

      expect(wrapper.text()).toContain('泰迪熊')
      expect(wrapper.text()).not.toContain('招财猫挂件')
    })
  })

  describe('MStockView（复用 @/types 的 InventoryItem）', () => {
    it('用 current_stock 渲染数量、barcode/product_barcode 渲染编码，并显示零库存徽标', async () => {
      mocks.stockApi.inventory.mockResolvedValue(
        inventoryResponse([
          inventoryItem(),
          inventoryItem({ product_id: 8, product_name: '拉链', barcode: '', product_barcode: 'Z09', current_stock: 0 }),
          inventoryItem({ product_id: 9, product_name: '大库存料', barcode: 'M09', current_stock: 1500 }),
        ]),
      )

      const wrapper = mount(MStockView)
      await flushPromises()

      expect(mocks.stockApi.inventory).toHaveBeenCalledWith({ page: 1, per_page: MOBILE_LIST_PAGE_SIZE })
      const text = wrapper.text()
      expect(text).toContain('PP棉')
      expect(text).toContain('M01')
      expect(text).toContain('120')
      expect(text).toContain('拉链')
      // barcode 为空串时回退 product_barcode
      expect(text).toContain('Z09')
      // 后端无安全库存字段 → 只判定零库存，且徽标真正可见（旧代码挂在恒为空的 warehouse_name 分支下）
      expect(text).toContain('零库存')
      expect(wrapper.find('.m-stock-qty-val.high').exists()).toBe(true)
    })

    it('「在库 / 零库存」筛选按 current_stock 判定', async () => {
      mocks.stockApi.inventory.mockResolvedValue(
        inventoryResponse([
          inventoryItem(),
          inventoryItem({ product_id: 8, product_name: '拉链', current_stock: 0 }),
        ]),
      )

      const wrapper = mount(MStockView)
      await flushPromises()

      const vm = wrapper.vm as unknown as { selectedTab: string }
      vm.selectedTab = 'zero'
      await nextTick()
      expect(wrapper.text()).toContain('拉链')
      expect(wrapper.text()).not.toContain('PP棉')

      vm.selectedTab = 'active'
      await nextTick()
      expect(wrapper.text()).toContain('PP棉')
      expect(wrapper.text()).not.toContain('拉链')
    })
  })

  describe('MPurchaseView（复用 @/types 的 PurchaseOrder / UnprocessedOrder）', () => {
    it('列表用 DTO 字段渲染，待审核行用 customer（DTO 无 customer_name）', async () => {
      mocks.purchaseApi.orders.mockResolvedValue({ orders: [purchaseOrder()], total: 1, pages: 1, current_page: 1 })
      mocks.purchaseApi.unprocessedOrders.mockResolvedValue({
        orders: [unprocessedOrder()],
        total: 1,
        pages: 1,
        current_page: 1,
      })
      mocks.purchaseApi.completed.mockResolvedValue({ orders: [], total: 0, pages: 1 })

      const wrapper = mount(MPurchaseView, { global: { plugins: [makeRouter()] } })
      await flushPromises()

      expect(mocks.purchaseApi.orders).toHaveBeenCalledWith({ page: 1, per_page: MOBILE_PAGE_SIZE })
      expect(wrapper.text()).toContain('供应商B · 100件')

      const vm = wrapper.vm as unknown as { activeTab: string }
      vm.activeTab = 'unprocessed'
      await nextTick()
      expect(wrapper.text()).toContain('20件 · 客户C')
    })

    it('详情时间按 DTO 字段收敛（采购单 create_time / 待审核订单 order_date）', async () => {
      mocks.purchaseApi.orders.mockResolvedValue({ orders: [], total: 0, pages: 1, current_page: 1 })
      mocks.purchaseApi.unprocessedOrders.mockResolvedValue({ orders: [], total: 0, pages: 1, current_page: 1 })
      mocks.purchaseApi.completed.mockResolvedValue({ orders: [], total: 0, pages: 1 })

      const wrapper = mount(MPurchaseView, { global: { plugins: [makeRouter()] } })
      await flushPromises()

      const vm = wrapper.vm as unknown as {
        showOrderDetail: (o: PurchaseOrder | UnprocessedOrder) => void
        detailTime: string
      }
      vm.showOrderDetail(purchaseOrder())
      await nextTick()
      expect(vm.detailTime).toBe('2026-09-01 10:00:00')

      vm.showOrderDetail(unprocessedOrder())
      await nextTick()
      expect(vm.detailTime).toBe('2026-09-02')
    })

    it('待生成 tab 只读展示（采购订单已改为自动生成，无人工审核按钮）', async () => {
      mocks.purchaseApi.orders.mockResolvedValue({ orders: [], total: 0, pages: 1, current_page: 1 })
      mocks.purchaseApi.unprocessedOrders.mockResolvedValue({
        orders: [unprocessedOrder(), unprocessedOrder({ id: 10, composite_id: 'stockin:3', product_name: '备货行' })],
        total: 2,
        pages: 1,
        current_page: 1,
      })
      mocks.purchaseApi.completed.mockResolvedValue({ orders: [], total: 0, pages: 1 })

      const wrapper = mount(MPurchaseView, { global: { plugins: [makeRouter()] } })
      await flushPromises()

      const vm = wrapper.vm as unknown as { activeTab: string }
      vm.activeTab = 'unprocessed'
      await nextTick()

      expect(wrapper.text()).toContain('待生成')
      expect(wrapper.text()).not.toContain('一键审核')
      expect(mocks.purchaseApi.oneClickGenerate).not.toHaveBeenCalled()
    })
  })

  describe('MProductionView（复用 @/types 的 DailySummary / MonthlySummary）', () => {
    it('日报读 DailySummary.departments/overall_*，月报读 MonthlySummary.monthly_departments/monthly_total_*', async () => {
      mocks.dailyProductionApi.dailySummary.mockResolvedValue(dailySummary())
      mocks.dailyProductionApi.monthlySummary.mockResolvedValue(monthlySummary())

      const wrapper = mount(MProductionView, { global: { plugins: [makeRouter()] } })
      await flushPromises()

      expect(wrapper.text()).toContain('充棉部')
      expect(wrapper.text()).toContain('100')
      expect(wrapper.text()).not.toContain('包装部')

      const vm = wrapper.vm as unknown as { viewTab: string }
      vm.viewTab = 'monthly'
      await flushPromises()

      expect(mocks.dailyProductionApi.monthlySummary).toHaveBeenCalledWith({
        year: expect.any(Number),
        month: expect.any(Number),
      })
      expect(wrapper.text()).toContain('包装部')
      expect(wrapper.text()).toContain('50')
      expect(wrapper.text()).not.toContain('充棉部')
    })
  })
})
