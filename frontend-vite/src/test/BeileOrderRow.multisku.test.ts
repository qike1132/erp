/**
 * 汇总列表「订单块」多 SKU 前端回归（2026-10-15 多 SKU 改版，对齐 /report 订单流水）。
 *
 * 覆盖：
 * - 一行一 SKU：产品名称/产品条码/订单数量/生产数量逐行渲染，订单级列跨行合并。
 * - 数量口径（单一真源）：逐 SKU = skuOrderQty / skuProductionQty / skuIsOrdered。
 * - 未下单：生产数量「—」，不编造 0（D-R2-1）。
 * - keyword 过滤逐 SKU（与导出 buildSummaryTbody 的 filterVisibleSkus 同源）。
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import BeileOrderRow from '@/views/beile-order/components/BeileOrderRow.vue'
import { beileColumns, beileMinWidth } from '@/views/beile-order/composables/useBeileOrders'
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

function mountRow(item: BeileOrderRowType, opts: { confirmable?: boolean; keyword?: string } = {}) {
  return mount(BeileOrderRow, {
    props: {
      item,
      confirmStatus: 'unconfirmed',
      isConfirming: false,
      highlightId: null,
      confirmable: opts.confirmable ?? true,
      selectable: false,
      selected: false,
      keyword: opts.keyword ?? '',
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

describe('BeileOrderRow 订单块（一行一 SKU + 订单级列跨行）', () => {
  it('多 SKU 订单：逐 SKU 一行（名称/条码/订单数量/生产数量），未下单生产数量「—」，无「合计」行', () => {
    const wrapper = mountRow(multiUnordered())

    // 逐 SKU 行：产品名称 X / Y 各占一行
    const names = wrapper.findAll('.bo-sku-name').map((n) => n.text())
    expect(names).toEqual(['X', 'Y'])

    // 逐 SKU 条码
    const barcodes = wrapper.findAll('.bo-barcode').map((n) => n.text())
    expect(barcodes).toEqual(['bX', 'bY'])

    // 逐 SKU 订单数量：10 / 20（客户订单原数量，未下单）
    const qtys = wrapper.findAll('.bo-qty').map((n) => n.text())
    expect(qtys).toEqual(['10', '20'])

    // 逐 SKU 生产数量：未下单不可派生 → 「—」（不编造 0）
    const prods = wrapper.findAll('.bo-prod')
    expect(prods.map((n) => n.text())).toEqual(['—', '—'])
    expect(prods.every((n) => n.classes().includes('bo-prod--none'))).toBe(true)

    // 2026-10-15：不再追加「合计」行
    expect(wrapper.find('.bo-total-label').exists()).toBe(false)
  })

  it('单 SKU 订单：一行一 SKU，无「合计」行', () => {
    const wrapper = mountRow(baseItem({
      items: [{ id: 1, product_name: 'X', quantity: 10 }],
      quantity: 10,
    }))
    expect(wrapper.findAll('.bo-sku-name')).toHaveLength(1)
    expect(wrapper.find('.bo-total-label').exists()).toBe(false)
    expect(wrapper.findAll('.bo-qty').map((n) => n.text())).toEqual(['10'])
  })

  it('命中逐 SKU 快照：逐 SKU 订单数量 = 采购单实际下单量（加粗），生产数量 = 下单量 + 备品', () => {
    const wrapper = mountRow(multiWithPoSku())

    // 逐 SKU 订单数量：10 / 20，均来自采购单实际下单量 → 加粗
    const qtys = wrapper.findAll('.bo-qty')
    expect(qtys.map((n) => n.text())).toEqual(['10', '20'])
    expect(qtys.every((n) => n.classes().includes('bo-qty--ordered'))).toBe(true)

    // 逐 SKU 生产数量：10+1=11 / 20+2=22
    expect(wrapper.findAll('.bo-prod').map((n) => n.text())).toEqual(['11', '22'])

    // 无「合计」行
    expect(wrapper.find('.bo-total-label').exists()).toBe(false)
  })

  it('订单类型徽章：订单记录显示「订单」', () => {
    const wrapper = mountRow(baseItem({ order_no: 'PO-100' }))
    const badge = wrapper.find('.bo-type-badge--order')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toBe('订单')
    // 不渲染订单号链接
    expect(wrapper.find('.bo-order-link').exists()).toBe(false)
  })

  it('备货记录显示「备货」徽章', () => {
    const wrapper = mountRow(baseItem({ record_type: 'stockin' }))
    expect(wrapper.find('.bo-type-badge--stockin').exists()).toBe(true)
    expect(wrapper.find('.bo-type-badge--stockin').text()).toBe('备货')
  })

  it('keyword 过滤逐 SKU（与导出 filterVisibleSkus 同源）：仅渲染命中 SKU，命中为空回退全部', () => {
    // 命中单个 SKU：只剩 Y 行
    const hit = mountRow(multiUnordered(), { keyword: 'y' })
    expect(hit.findAll('.bo-sku-name').map((n) => n.text())).toEqual(['Y'])
    expect(hit.find('.bo-total-label').exists()).toBe(false)

    // 无命中：回退全部 SKU（避免空列表）
    const miss = mountRow(multiUnordered(), { keyword: 'zzz' })
    expect(miss.findAll('.bo-sku-name').map((n) => n.text())).toEqual(['X', 'Y'])
    expect(miss.find('.bo-total-label').exists()).toBe(false)
  })

  it('订单级列跨行合并：订单级单元格 grid-row 跨 span 行（= SKU 行数）', () => {
    const wrapper = mountRow(multiUnordered())
    // 2 SKU = span 2
    const orderCell = wrapper.find('.bo-td-order-no')
    expect(orderCell.attributes('style')).toContain('grid-row: 1 / span 2')
  })

  it('订单块行高：下限 56px、上限 auto（内容可撑高，不硬裁）', () => {
    const wrapper = mountRow(multiUnordered())
    const style = wrapper.find('.bo-block').attributes('style') ?? ''
    // 只取 grid-auto-rows 那一条声明（避免匹配到 grid-template-columns 里的 minmax）
    const autoRowsDecl = style
      .split(';')
      .map((s) => s.trim())
      .find((s) => s.startsWith('grid-auto-rows')) ?? ''
    expect(autoRowsDecl).toContain('minmax')
    expect(autoRowsDecl).toContain('auto')
  })

  it('产品名称单行显示：名称单元格 nowrap（超长省略号 + hover 看全名）', () => {
    // 需求（2026-10-15）：产品名称尽量单行显示，超长用省略号截断，hover 看全名。
    const longName = 'MINI FAMILY系列（第8款花环毛绒挂件10个装小礼盒，含PDQ）'
    const wrapper = mountRow(baseItem({
      items: [{ id: 1, product_name: longName, quantity: 10 }],
      quantity: 10,
    }))

    const nameCell = wrapper.findAll('.bo-td').find((c) => c.find('.bo-sku-name').exists())
    expect(nameCell).toBeTruthy()
    // 单行：单元格 nowrap → .bo-sku-name 的 text-overflow:ellipsis 生效
    expect(nameCell!.classes()).toContain('bo-td-nowrap')
    // 超长时仍可 hover 看全名
    expect(nameCell!.find('.bo-sku-name').attributes('title')).toBe(longName)
  })

  it('列宽：收窄次要列、产品名称列加宽；订单号/下单时间不截断、总宽不增（不新增横向滚动）', () => {
    const cols = beileColumns({ canPrint: false, confirmStatus: 'unconfirmed' })
    const width = (k: string) => cols.find((c) => c.key === k)!.width as number

    // 产品名称列显著加宽（180 → 375）
    expect(width('productName')).toBeGreaterThanOrEqual(370)
    // 收窄的次要列
    expect(width('type')).toBeLessThanOrEqual(80)
    expect(width('customer')).toBeLessThanOrEqual(130)
    expect(width('factory')).toBeLessThanOrEqual(90)
    expect(width('productBarcode')).toBeLessThanOrEqual(125)
    expect(width('orderQty')).toBeLessThanOrEqual(95)
    expect(width('opened')).toBeLessThanOrEqual(95)
    // 单号 16 字符 / 时间到分 16 字符：保持够宽不被截断
    expect(width('orderNo')).toBeGreaterThanOrEqual(140)
    expect(width('date')).toBeGreaterThanOrEqual(135)
    // 总宽（各列宽之和，flex 按 160 保底）不超过原值 1600，故不新增横向滚动
    expect(beileMinWidth(cols)).toBeLessThanOrEqual(1600)
  })

  it('confirmable 门控：有权限（true）渲染确认按钮，无权限（false）隐藏', () => {
    // 有权限：确认按钮存在
    const withPerm = mountRow(baseItem({ confirmed: false }))
    expect(withPerm.find('.bo-confirm-btn').exists()).toBe(true)

    // 无权限：确认按钮不渲染（beile_order_confirm 门控）
    const noPerm = mountRow(baseItem({ confirmed: false }), { confirmable: false })
    expect(noPerm.find('.bo-confirm-btn').exists()).toBe(false)
  })
})
