/**
 * 汇总下单弹窗「逐 SKU 分行」回归测试（2026-09-18）。
 *
 * 背景：多 SKU 客户订单汇总下单后，弹窗「产品名称」只显示 1 个 SKU。后端已修
 * （产品名不再被首个 SKU 覆盖、物料取全部 SKU 并集），并在分组上新增 `skus[]`；
 * 本文件锁定**前端展示契约**：
 *
 *   C1 多 SKU：产品名称 / 订单数量 两列逐 SKU 分行，并追加「合计」子行；
 *   C2 合计口径 = 订单级真值 `getGroupOrderQty`（不依赖逐 SKU 之和）；
 *   C4 单 SKU / 旧后端（无 skus）→ 只一行，与改动前逐字一致（零回归）；
 *   C5 打印预览 / Excel 导出（buildFactoryHtml）与屏幕同源，逐 SKU 以 <br> 分行。
 *
 * 物料列仍为订单级：采购单侧物料数量是跨 SKU 合并值，无法拆分到 SKU，前端不编造数字。
 */
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'

vi.mock('@/api', () => ({
  purchaseApi: {
    orders: vi.fn(),
    unprocessedOrders: vi.fn(),
    factorySummary: vi.fn(),
    supplierSummary: vi.fn(),
    saveFactoryEdits: vi.fn(),
    supplierSummaryExport: vi.fn(),
  },
}))

import SummaryModal from '@/views/purchase/components/SummaryModal.vue'
import {
  buildFactoryHtml,
  buildSkuDisplayLines,
  calcSpareQuantity,
  magnifyByLossRate,
} from '@/views/purchase/composables/useSummaryModal'
import type { FactorySummaryData, FactoryGroup } from '@/views/purchase/composables/useSummaryModal'
import { fmtQty } from '@/utils/formatQty'

const stubs = {
  UiDialog: { template: '<div class="ui-dialog-stub"><slot name="title" /><slot /></div>' },
}

/** 4 SKU 订单（对齐真实单 CG-20260918-0008：奥飞，4 × 999,111） */
function multiSkuGroup(): FactoryGroup {
  return {
    customer_name: '奥飞',
    product_name: 'Nommi糯米儿-宝藏收藏家系列毛绒盲盒、企鹅的订单、变形金刚、妹妹二代',
    product_quantity: 3996444,
    skus: [
      { product_name: '妹妹二代', product_barcode: '6978946330580', order_qty: 999111 },
      { product_name: 'Nommi糯米儿-宝藏收藏家系列毛绒盲盒', product_barcode: '6978946330588', order_qty: 999111 },
      { product_name: '企鹅的订单', product_barcode: '', order_qty: 999111 },
      { product_name: '变形金刚', product_barcode: '', order_qty: 999111 },
    ],
    suppliers: [
      {
        supplier_name: '美易达',
        fabrics: [{ fabric_name: '安伦', specification: '11', quantity: 239786.64, unit: '码' }],
      },
    ],
  }
}

function singleSkuGroup(): FactoryGroup {
  return {
    customer_name: 'TOP TOY',
    product_name: '变形金刚',
    product_quantity: 969461,
    skus: [{ product_name: '变形金刚', product_barcode: '', order_qty: 969461 }],
    suppliers: [
      { supplier_name: '三虎', fabrics: [{ fabric_name: '小兔毛', specification: '17', quantity: 139875.54, unit: '码' }] },
    ],
  }
}

function dataWith(group: FactoryGroup): FactorySummaryData {
  return { success: true, order_count: 1, spare_rate: 10, groups: [group] }
}

function mountModal(group: FactoryGroup, lossRate = 10) {
  return mount(SummaryModal, {
    props: {
      open: true,
      factoryData: dataWith(group),
      supplierData: { success: true, order_count: 1, materials: [] },
      editMode: false,
      lossRate,
      orderCount: 1,
      supplierGroups: [],
    },
    global: { stubs },
    attachTo: document.body,
  })
}

/** 取首个数据行的单元格（客户 / 产品名称 / 订单数量 / 备品数量 / 供应商 …） */
function firstRowCells(wrapper: ReturnType<typeof mountModal>) {
  const rows = wrapper.findAll('tbody tr')
  expect(rows.length).toBeGreaterThan(0)
  return rows[0]!.findAll('td')
}

describe('buildSkuDisplayLines（逐 SKU 展示行唯一来源）', () => {
  it('C1/C2 多 SKU：4 个 SKU 各一行 + 「合计」子行，合计取订单级真值', () => {
    const lines = buildSkuDisplayLines(multiSkuGroup())

    expect(lines.map((l) => l.name)).toEqual([
      '妹妹二代',
      'Nommi糯米儿-宝藏收藏家系列毛绒盲盒',
      '企鹅的订单',
      '变形金刚',
      '合计',
    ])
    expect(lines.slice(0, 4).map((l) => l.qty)).toEqual([999111, 999111, 999111, 999111])
    expect(lines[4]!.qty).toBe(3996444)
    expect(lines.slice(0, 4).every((l) => l.isTotal === false)).toBe(true)
    expect(lines[4]!.isTotal).toBe(true)
    // 备品已改为逐布料行计算，SKU 行只承载名称/数量
    expect(lines.every((l) => !('spare' in l))).toBe(true)
  })

  it('C4 单 SKU 只一行（不产生「合计」子行），与改动前逐字一致', () => {
    const lines = buildSkuDisplayLines(singleSkuGroup())

    expect(lines).toHaveLength(1)
    expect(lines[0]).toEqual({ name: '变形金刚', qty: 969461, isTotal: false })
  })

  it('C4 旧后端不返回 skus 时降级为订单级单行（零回归）', () => {
    const legacy: FactoryGroup = {
      customer_name: '奥飞',
      product_name: '妹妹二代、企鹅的订单',
      product_quantity: 20000,
      suppliers: [],
    }

    const lines = buildSkuDisplayLines(legacy)

    expect(lines).toHaveLength(1)
    expect(lines[0]!.name).toBe('妹妹二代、企鹅的订单')
    expect(lines[0]!.qty).toBe(20000)
  })
})

describe('buildFactoryHtml（打印预览 / Excel 导出与屏幕同源）', () => {
  it('C5 多 SKU：产品名称与订单数量单元格以 <br> 逐 SKU 分行，「合计」加粗', () => {
    const html = buildFactoryHtml(dataWith(multiSkuGroup()), 10)
    const fabricQty = multiSkuGroup().suppliers[0]!.fabrics[0]!.quantity

    expect(html).toContain('妹妹二代<br>Nommi糯米儿-宝藏收藏家系列毛绒盲盒<br>企鹅的订单<br>变形金刚<br><strong>合计</strong>')
    expect(html).toContain(`<strong>${fmtQty(3996444)}</strong>`)
    // 备品列已改为逐布料行：239786.64 × 10‰ → ceil=2398；数量列按同率放大展示
    expect(html).toContain(`<td>${fmtQty(calcSpareQuantity(fabricQty, 10))}</td>`)
    expect(html).toContain(`<td>${Math.ceil(magnifyByLossRate(fabricQty, 10))}</td>`)
  })

  it('C4 单 SKU：不出现 <br> 与「合计」，输出与改动前一致', () => {
    const html = buildFactoryHtml(dataWith(singleSkuGroup()), 10)

    expect(html).not.toContain('<br>')
    expect(html).not.toContain('合计')
    expect(html).toContain('变形金刚')
    expect(html).toContain(fmtQty(969461))
  })
})

describe('SummaryModal 渲染（逐 SKU 分行）', () => {
  it('C1 多 SKU：产品名称 / 订单数量各 5 行，备品为该布料行 ceil 值，末行为「合计」', async () => {
    const wrapper = mountModal(multiSkuGroup())
    const cells = firstRowCells(wrapper)

    // 列序：0 客户 | 1 产品名称 | 2 订单数量 | 3 备品数量 | 4 供应商 …
    const nameLines = cells[1]!.findAll('.sm-sku-line')
    const qtyLines = cells[2]!.findAll('.sm-sku-line')

    expect(nameLines.map((n) => n.text())).toEqual([
      '妹妹二代',
      'Nommi糯米儿-宝藏收藏家系列毛绒盲盒',
      '企鹅的订单',
      '变形金刚',
      '合计',
    ])
    expect(qtyLines).toHaveLength(5)
    expect(cells[3]!.findAll('.sm-sku-line')).toHaveLength(0)
    expect(cells[3]!.text()).toBe(fmtQty(2398))
    expect(nameLines[4]!.classes()).toContain('sm-sku-line--total')
    expect(nameLines[0]!.classes()).not.toContain('sm-sku-line--total')

    wrapper.unmount()
  })

  it('C4 单 SKU：三列各只有 1 行，不出现「合计」子行', async () => {
    const wrapper = mountModal(singleSkuGroup())
    const cells = firstRowCells(wrapper)

    expect(cells[1]!.findAll('.sm-sku-line')).toHaveLength(1)
    expect(cells[1]!.text()).toBe('变形金刚')
    expect(cells[2]!.text()).toBe(fmtQty(969461))
    expect(wrapper.find('.sm-sku-line--total').exists()).toBe(false)

    wrapper.unmount()
  })
})
