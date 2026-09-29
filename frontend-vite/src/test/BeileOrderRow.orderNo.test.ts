/**
 * 贝乐汇总行：订单号列回归锁（2026-09-29）。
 *
 * 背景：多 SKU 改版把原「订单号」列换成了「订单类型」徽章，列表里再也看不到单号。
 * 现按变体 B 恢复 —— **保留类型列**，订单号紧随其后。
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import BeileOrderRow from '@/views/beile-order/components/BeileOrderRow.vue'
import type { BeileOrderRow as BeileOrderRowType } from '@/views/beile-order/composables/useBeileOrders'

function baseItem(extra: Record<string, unknown> = {}): BeileOrderRowType {
  return {
    id: 1,
    record_type: 'order',
    order_no: 'PO-20260929-0008',
    customer: 'C1',
    order_date: '2026-09-29',
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

function mountRow(item: BeileOrderRowType) {
  return mount(BeileOrderRow, {
    props: {
      item,
      confirmStatus: 'unconfirmed',
      isConfirming: false,
      highlightId: null,
      confirmable: true,
      selectable: false,
      selected: false,
    },
    global: { stubs: { UiCheckbox: true } },
  })
}

describe('BeileOrderRow 订单号列', () => {
  it('渲染订单号', () => {
    expect(mountRow(baseItem()).text()).toContain('PO-20260929-0008')
  })

  it('订单号列紧随「订单类型」之后（变体 B：类型在前）', () => {
    const cells = mountRow(baseItem()).findAll('.bo-td')
    const typeIdx = cells.findIndex((c) => c.find('.bo-type-badge').exists())
    // ★ 类在单元格自身上，用 classes() 而非 find()（后者只找后代）
    const noIdx = cells.findIndex((c) => c.classes().includes('bo-td-order-no'))
    expect(typeIdx).toBeGreaterThanOrEqual(0)
    expect(noIdx).toBe(typeIdx + 1)
  })

  it('备货行同样显示订单号', () => {
    const w = mountRow(baseItem({ record_type: 'stockin', order_no: 'BH-20260929-0001' }))
    expect(w.text()).toContain('BH-20260929-0001')
  })

  it('订单号缺失时回落占位符，不留空白单元格', () => {
    const cell = mountRow(baseItem({ order_no: undefined })).find('.bo-td-order-no')
    expect(cell.exists()).toBe(true)
    expect(cell.text().trim()).not.toBe('')
  })
})
