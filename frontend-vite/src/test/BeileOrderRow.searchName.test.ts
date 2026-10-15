/**
 * 搜索态行展示回归（2026-10-15 多 SKU 改版后）：keyword 收窄逐 SKU 行 + SKU 级数量。
 *
 * 需求（2026-09-19 第二轮）：搜索后只显示命中的产品，数量只统计所搜索 SKU 对应的数量；
 * 2026-10-15 多 SKU 改版后，「产品名称」为逐 SKU 常驻列（原搜索态专属的顿号拼接列已取消），
 * keyword 通过 filterVisibleSkus 收窄逐 SKU 行（与导出 buildSummaryTbody 同源）。
 *
 * 分工：后端 beile.py 在搜索时把 items 收窄为命中 SKU 并重算订单级数量
 * （test_beile_orders.py::test_beile_list_search_narrows_items_and_qty_to_matched_skus）；
 * 本文件验证行组件在搜索态的呈现（逐 SKU 名称列 / keyword 收窄 / 数量读收窄后的口径）。
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

function mountRow(item: BeileOrderRowType, keyword = '') {
  return mount(BeileOrderRow, {
    props: {
      item,
      confirmStatus: 'unconfirmed',
      isConfirming: false,
      highlightId: null,
      confirmable: true,
      selectable: false,
      selected: false,
      keyword,
    },
    global: { stubs: { UiCheckbox: true } },
  })
}

describe('BeileOrderRow 搜索态：keyword 收窄逐 SKU 行 + SKU 级数量', () => {
  it('搜索态单 SKU 命中：显示命中产品名，数量 = 收窄后 SKU 数量 60（非全单合计）', () => {
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
    const wrapper = mountRow(item, '变形金刚')

    // 逐 SKU 产品名称列（常驻列，逐行渲染）
    const names = wrapper.findAll('.bo-sku-name')
    expect(names.length).toBe(1)
    expect(names[0]!.text()).toBe('变形金刚')

    // 数量列只统计命中 SKU（后端收窄 + 前端 filterVisibleSkus 同键生效）
    expect(wrapper.findAll('.bo-qty').map((n) => n.text())).toEqual(['60'])
    // 未下单：生产数量「—」
    expect(wrapper.findAll('.bo-prod').map((n) => n.text())).toEqual(['—'])
    // 单 SKU：无合计行
    expect(wrapper.find('.bo-total-label').exists()).toBe(false)
  })

  it('搜索态多 SKU 命中：逐 SKU 名称/数量各占一行', () => {
    const item = baseItem({
      is_ordered: true,
      purchase_order_qty: 76,
      spare_quantity: 7,
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
    const wrapper = mountRow(item, '变形金刚')

    // 逐 SKU 名称（不再顿号拼接到单格）
    expect(wrapper.findAll('.bo-sku-name').map((n) => n.text())).toEqual(['变形金刚', '变形金刚plus'])
    // 逐 SKU 订单数量 = 各自采购单实际下单量 66 / 10
    expect(wrapper.findAll('.bo-qty').map((n) => n.text())).toEqual(['66', '10'])
    // 逐 SKU 生产数量 = 下单量 + 备品
    expect(wrapper.findAll('.bo-prod').map((n) => n.text())).toEqual(['72', '11'])
    // 无「合计」行
    expect(wrapper.find('.bo-total-label').exists()).toBe(false)
  })

  it('keyword 只命中部分 SKU：仅渲染命中 SKU 行（filterVisibleSkus，与导出同源）', () => {
    const item = baseItem({
      is_ordered: false,
      purchase_order_qty: 0,
      spare_quantity: 0,
      items: [
        { id: 1, product_name: '变形金刚', product_barcode: '690001', quantity: 60, note: '' },
        { id: 2, product_name: '奥特曼', product_barcode: '690002', quantity: 40, note: '' },
      ],
    })
    const wrapper = mountRow(item, '变形金刚')
    expect(wrapper.findAll('.bo-sku-name').map((n) => n.text())).toEqual(['变形金刚'])
    expect(wrapper.find('.bo-total-label').exists()).toBe(false)
  })

  it('非搜索态（keyword 空）：渲染全部 SKU', () => {
    const item = baseItem({
      is_ordered: false,
      purchase_order_qty: 0,
      spare_quantity: 0,
      items: [
        { id: 1, product_name: '变形金刚', product_barcode: '690001', quantity: 60, note: '' },
        { id: 2, product_name: '奥特曼', product_barcode: '690002', quantity: 40, note: '' },
      ],
    })
    const wrapper = mountRow(item)
    expect(wrapper.findAll('.bo-sku-name').map((n) => n.text())).toEqual(['变形金刚', '奥特曼'])
  })

  it('备货行（无 items 明细）：逐 SKU 行回落订单级 product_name（单行）', () => {
    const item = baseItem({
      record_type: 'stockin',
      product_name: '变形金刚',
      items: [],
    })
    const wrapper = mountRow(item, '变形金刚')
    const names = wrapper.findAll('.bo-sku-name')
    expect(names.length).toBe(1)
    expect(names[0]!.text()).toBe('变形金刚')
  })
})
