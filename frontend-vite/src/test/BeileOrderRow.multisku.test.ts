/**
 * 汇总列表行（两级结构之一级）前端回归：BeileOrderRow 订单级汇总单行。
 *
 * 覆盖：
 * - 多 SKU 订单：行内只展示订单级汇总（订单数量 = rowTotal、生产数量 = rowTotalProd），
 *   不再内嵌逐 SKU 行；用 SKU 数徽章提示多 SKU，点击订单号进入详情。
 * - 命中逐 SKU 快照时订单数量取采购单实际下单量（加粗），生产数量 = 订单 + 备品。
 * - 未下单：生产数量「—」，订单数量 = 各 SKU 客户订单量之和。
 * - 口径稳定（RC-3）：订单级汇总不随筛选变化。
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import BeileOrderRow from '@/views/beile-order/components/BeileOrderRow.vue'
import type { BeileOrderRow as BeileOrderRowType } from '@/views/beile-order/composables/useBeileOrders'

function baseItem(extra: Record<string, unknown> = {}): BeileOrderRowType {
  return {
    id: 1,
    record_type: 'order',
    order_no: 'PO-1',
    customer: 'C1',
    order_date: '2026-09-01',
    product_name: 'X',
    product_id: 1,
    quantity: 30,
    deduct_quantity: 0,
    deduct_stock: false,
    note: '',
    status: '',
    factories: ['湖北'],
    confirmed: false,
    ...extra,
  } as unknown as BeileOrderRowType
}

function mountRow(item: BeileOrderRowType, confirmable = true) {
  return mount(BeileOrderRow, {
    props: {
      item,
      confirmStatus: 'unconfirmed',
      isConfirming: false,
      highlightId: null,
      confirmable,
      selectable: false,
      selected: false,
    },
    global: { stubs: { UiCheckbox: true } },
  })
}

/** 2 SKU（X=10 / Y=20），未下单，无逐 SKU 快照 */
function multiUnordered() {
  return baseItem({
    is_ordered: false,
    purchase_order_qty: 0,
    spare_quantity: 0,
    items: [
      { id: 1, product_name: 'X', product_barcode: 'bX', quantity: 10, note: '' },
      { id: 2, product_name: 'Y', product_barcode: 'bY', quantity: 20, note: '' },
    ],
  })
}

/** 2 SKU，已下单且命中逐 SKU 快照（X: 10/备1，Y: 20/备2；订单合计 30/备3） */
function multiWithPoSku() {
  return baseItem({
    is_ordered: true,
    purchase_order_qty: 30,
    spare_quantity: 3,
    spare_rate: 50,
    items: [
      {
        id: 1, product_name: 'X', product_barcode: 'bX', quantity: 10, note: '',
        per_sku_source: 'po_sku', purchase_order_qty: 10, spare_quantity: 1, is_ordered: true,
      },
      {
        id: 2, product_name: 'Y', product_barcode: 'bY', quantity: 20, note: '',
        per_sku_source: 'po_sku', purchase_order_qty: 20, spare_quantity: 2, is_ordered: true,
      },
    ],
  })
}

describe('BeileOrderRow 汇总单行（两级结构之一级）', () => {
  it('多 SKU 订单：行内无 SKU 子表/折叠，订单数量 = 订单级汇总 30，SKU 数徽章显示 2 项', () => {
    const wrapper = mountRow(multiUnordered())

    // 无折叠开关、无 SKU 子表
    expect(wrapper.find('.bo-sku-toggle').exists()).toBe(false)
    expect(wrapper.find('.bo-sku-table').exists()).toBe(false)

    // SKU 数徽章
    const skuCount = wrapper.find('.bo-sku-count')
    expect(skuCount.exists()).toBe(true)
    expect(skuCount.text()).toBe('2 项')
    expect(skuCount.classes()).toContain('bo-sku-count--multi')

    // 订单数量 = 30（订单级汇总）
    expect(wrapper.find('.bo-qty').text()).toBe('30')
    // 生产数量 = —（未下单不可派生）
    expect(wrapper.find('.bo-prod').exists()).toBe(true)
    expect(wrapper.find('.bo-prod').text()).toBe('—')
  })

  it('单 SKU 订单：SKU 数徽章为「1 项」且不加多 SKU 高亮', () => {
    const wrapper = mountRow(baseItem({
      items: [{ id: 1, product_name: 'X', quantity: 10 }],
      quantity: 10,
    }))
    const skuCount = wrapper.find('.bo-sku-count')
    expect(skuCount.text()).toBe('1 项')
    expect(skuCount.classes()).not.toContain('bo-sku-count--multi')
  })

  it('命中逐 SKU 快照：订单数量加粗 = 采购单实际下单量 30，生产数量 = 30 + 3 = 33', () => {
    const wrapper = mountRow(multiWithPoSku())
    expect(wrapper.find('.bo-qty').text()).toBe('30')
    expect(wrapper.find('.bo-qty').classes()).toContain('bo-qty--ordered')
    expect(wrapper.find('.bo-prod').text()).toBe('33')
  })

  it('订单类型徽章：订单记录显示「订单」，点击整行发出 open 事件', async () => {
    const wrapper = mountRow(baseItem({ order_no: 'PO-100' }))
    const badge = wrapper.find('.bo-type-badge--order')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toBe('订单')
    // 不渲染订单号链接
    expect(wrapper.find('.bo-order-link').exists()).toBe(false)
    await wrapper.find('.bo-grid-row').trigger('click')
    expect(wrapper.emitted('open')).toBeTruthy()
    expect(wrapper.emitted('open')![0]).toEqual([expect.objectContaining({ order_no: 'PO-100' })])
  })

  it('备货记录显示「备货」徽章', () => {
    const wrapper = mountRow(baseItem({ record_type: 'stockin' }))
    expect(wrapper.find('.bo-type-badge--stockin').exists()).toBe(true)
    expect(wrapper.find('.bo-type-badge--stockin').text()).toBe('备货')
  })

  it('口径稳定（RC-3）：订单级汇总 30 不随筛选而变化（行内不再按关键字过滤 SKU）', () => {
    const wrapper = mountRow(multiUnordered())
    expect(wrapper.find('.bo-qty').text()).toBe('30')
  })

  it('confirmable 门控：有权限（true）渲染确认按钮，无权限（false）隐藏', () => {
    // 有权限：确认按钮存在
    const withPerm = mountRow(baseItem({ confirmed: false }))
    expect(withPerm.find('.bo-confirm-btn').exists()).toBe(true)

    // 无权限：确认按钮不渲染（beile_order_confirm 门控）
    const noPerm = mountRow(baseItem({ confirmed: false }), false)
    expect(noPerm.find('.bo-confirm-btn').exists()).toBe(false)
  })
})
