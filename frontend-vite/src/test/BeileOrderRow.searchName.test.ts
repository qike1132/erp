/**
 * 搜索态行展示回归：BeileOrderRow「产品名称」列 + SKU 级数量。
 *
 * 需求（2026-09-19 第二轮）：搜索后列表新增「产品名称」表头，显示搜索到的产品名；
 * 「订单数量 / 生产数量」只统计所搜索 SKU 对应的数量，不显示整个订单的合计。
 *
 * 分工：后端 beile.py 在搜索时把 items 收窄为命中 SKU 并重算订单级数量
 * （test_beile_orders.py::test_beile_list_search_narrows_items_and_qty_to_matched_skus）；
 * 本文件验证行组件在搜索态的呈现（列出现 / 名称 join / 数量读收窄后的口径）。
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import BeileOrderRow from '@/views/beile-order/components/BeileOrderRow.vue'
import type { BeileOrderRow as BeileOrderRowType } from '@/views/beile-order/composables/useBeileOrders'

function baseItem(extra: Record<string, unknown> = {}): BeileOrderRowType {
  return {
    id: 15,
    record_type: 'order',
    order_no: 'PO-15',
    customer: '多SKU客户',
    order_date: '2026-09-05 10:00',
    product_name: '变形金刚',
    product_id: 1,
    quantity: 60,
    deduct_quantity: 0,
    deduct_stock: false,
    note: '',
    status: '',
    factories: ['湖北'],
    confirmed: false,
    ...extra,
  } as unknown as BeileOrderRowType
}

function mountRow(item: BeileOrderRowType, hasKeyword: boolean) {
  return mount(BeileOrderRow, {
    props: {
      item,
      confirmStatus: 'unconfirmed',
      isConfirming: false,
      highlightId: null,
      selectable: false,
      selected: false,
      hasKeyword,
    },
    global: { stubs: { UiCheckbox: true } },
  })
}

describe('BeileOrderRow 搜索态：产品名称列 + SKU 级数量', () => {
  it('搜索态：显示命中产品名（多 SKU 顿号连接），数量 = 收窄后 items 合计 60（非全单 100）', () => {
    // 服务端收窄后形态：items 只含命中 SKU「变形金刚」；订单级数量已按命中集合重算
    const item = baseItem({
      is_ordered: false,
      purchase_order_qty: 60,
      spare_quantity: 0,
      quantity: 60,
      items: [
        { id: 1, product_name: '变形金刚', product_barcode: '690001', quantity: 60, note: '' },
      ],
    })
    const wrapper = mountRow(item, true)

    const name = wrapper.find('.bo-search-name')
    expect(name.exists()).toBe(true)
    expect(name.text()).toBe('变形金刚')

    // 数量列只统计命中 SKU（后端收窄保证；此处行读到的就是收窄后的口径）
    expect(wrapper.find('.bo-qty').text()).toBe('60')
    // 未下单：生产数量「—」
    expect(wrapper.find('.bo-prod').text()).toBe('—')
  })

  it('搜索态多 SKU 命中：名称顿号连接；已下单快照场景数量 = 命中集合 rollup', () => {
    const item = baseItem({
      is_ordered: true,
      purchase_order_qty: 66,
      spare_quantity: 6,
      items: [
        {
          id: 1, product_name: '变形金刚', product_barcode: '690001', quantity: 60, note: '',
          per_sku_source: 'po_sku', purchase_order_qty: 66, spare_quantity: 6, is_ordered: true,
        },
        {
          id: 2, product_name: '变形金刚plus', product_barcode: '690009', quantity: 20, note: '',
          per_sku_source: 'po_sku', purchase_order_qty: 10, spare_quantity: 1, is_ordered: true,
        },
      ],
    })
    const wrapper = mountRow(item, true)

    expect(wrapper.find('.bo-search-name').text()).toBe('变形金刚、变形金刚plus')
    // 订单级数量 = purchase_order_qty（命中集合 rollup，由后端保证）
    expect(wrapper.find('.bo-qty').text()).toBe('66')
    // 生产数量 = 订单数量 + 备品 = 66 + 6
    expect(wrapper.find('.bo-prod').text()).toBe('72')
  })

  it('非搜索态（hasKeyword 缺省 / false）：不渲染产品名称列', () => {
    const item = baseItem({
      is_ordered: false,
      purchase_order_qty: 0,
      spare_quantity: 0,
      items: [{ id: 1, product_name: '变形金刚', product_barcode: '690001', quantity: 60, note: '' }],
    })
    expect(mountRow(item, false).find('.bo-search-name').exists()).toBe(false)
  })

  it('备货行（无 items 明细）：产品名称回落订单级 product_name', () => {
    const item = baseItem({
      record_type: 'stockin',
      product_name: '变形金刚',
      items: [],
    })
    const wrapper = mountRow(item, true)
    expect(wrapper.find('.bo-search-name').text()).toBe('变形金刚')
  })
})
