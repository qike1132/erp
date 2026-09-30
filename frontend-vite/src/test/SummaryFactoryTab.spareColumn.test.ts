/**
 * 汇总下单「备品数量」列回归测试（2026-09-30）。
 *
 * 需求（用户 2026-09-30 裁决）：
 *   A1 「备品数量」列置于「订单数量」右侧（第 4 列），屏幕 / 打印 / 导出三处同步；
 *   A2 口径固定为 **备品 = ceil(订单数量 × 订单级率‰)**；
 *   A3 **自定义（逐布料行）损耗率不影响备品** —— 材料损耗率是 40%-100% 量级、
 *      备品率是 0.5%-3% 量级，混用会虚高（生产实证：单张单 150 → 4500，30 倍）；
 *   A4 多 SKU 逐 SKU `ceil` 后求和（不是先求和再取整），与后端 resync_po_sku_spare
 *      及 /beile-order 的逐 SKU 口径一致；
 *   A5 率未设（0）→ 显示 0（确定值，不是「无法派生」）；
 *   A6 不加表尾合计。
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
  FACTORY_TABLE_HEAD,
  buildFactoryHtml,
  buildSkuDisplayLines,
  calcSpareQuantity,
} from '@/views/purchase/composables/useSummaryModal'
import type { FactoryGroup, FactorySummaryData } from '@/views/purchase/composables/useSummaryModal'

const stubs = {
  UiDialog: { template: '<div class="ui-dialog-stub"><slot name="title" /><slot /></div>' },
}

/** 单 SKU：订单数量 10000（对齐真实单 CG-20260930-0002 的数量级） */
function singleSkuGroup(): FactoryGroup {
  return {
    customer_name: 'MINISO国际',
    product_name: '鲨鱼',
    product_quantity: 10000,
    skus: [{ product_name: '鲨鱼', product_barcode: '6978946330000', order_qty: 10000 }],
    suppliers: [
      {
        supplier_name: '超柔供应商',
        // 行率 450‰ 是**材料损耗**量级：它只影响「数量」列加放，不得影响备品
        fabrics: [{ fabric_name: '蓝色超柔', specification: '223', quantity: 890, unit: '码', loss_rate: 450, item_ids: [1] }],
      },
    ],
  }
}

/** 3 SKU × 各 1 件：用于证明「逐 SKU 取整后求和」≠「先求和再取整」 */
function tinyMultiSkuGroup(): FactoryGroup {
  return {
    customer_name: '客户T',
    product_name: 'A、B、C',
    product_quantity: 3,
    skus: [
      { product_name: 'A', product_barcode: '', order_qty: 1 },
      { product_name: 'B', product_barcode: '', order_qty: 1 },
      { product_name: 'C', product_barcode: '', order_qty: 1 },
    ],
    suppliers: [{ supplier_name: 'S', fabrics: [{ fabric_name: '布', specification: '1', quantity: 1, unit: '码' }] }],
  }
}

function dataWith(group: FactoryGroup, spareRate = 15): FactorySummaryData {
  return { success: true, order_count: 1, spare_rate: spareRate, groups: [group] }
}

function mountModal(group: FactoryGroup, opts: {
  lossRate?: number
  groupSpareRates?: number[]
  fabricLossRates?: number[][][]
} = {}) {
  return mount(SummaryModal, {
    props: {
      open: true,
      factoryData: dataWith(group, opts.lossRate ?? 15),
      supplierData: { success: true, order_count: 1, materials: [] },
      editMode: false,
      lossRate: opts.lossRate ?? 15,
      orderCount: 1,
      supplierGroups: [],
      groupSpareRates: opts.groupSpareRates,
      fabricLossRates: opts.fabricLossRates,
    },
    global: { stubs },
    attachTo: document.body,
  })
}

/** 表头文本数组 */
function headerTexts(wrapper: ReturnType<typeof mountModal>): string[] {
  return wrapper.findAll('thead th').map((th) => th.text())
}

/** 首个数据行的单元格 */
function firstRowCells(wrapper: ReturnType<typeof mountModal>) {
  const rows = wrapper.findAll('tbody tr')
  expect(rows.length).toBeGreaterThan(0)
  return rows[0]!.findAll('td')
}

describe('calcSpareQuantity（备品口径唯一实现）', () => {
  it('ceil(qty × rate‰)：10000 × 15‰ → 150', () => {
    expect(calcSpareQuantity(10000, 15)).toBe(150)
  })

  it('向上取整：1000 × 5‰ = 5.0 → 5；1001 × 5‰ = 5.005 → 6', () => {
    expect(calcSpareQuantity(1000, 5)).toBe(5)
    expect(calcSpareQuantity(1001, 5)).toBe(6)
  })

  it('率未设 / 为 0 / 为负 / 非法 → 0（确定值）', () => {
    expect(calcSpareQuantity(10000, 0)).toBe(0)
    expect(calcSpareQuantity(10000, -5)).toBe(0)
    expect(calcSpareQuantity(10000, Number.NaN)).toBe(0)
    expect(calcSpareQuantity(10000, Number.POSITIVE_INFINITY)).toBe(0)
  })

  it('数量为 0 / 负 / 非法 → 0', () => {
    expect(calcSpareQuantity(0, 15)).toBe(0)
    expect(calcSpareQuantity(-1, 15)).toBe(0)
    expect(calcSpareQuantity(Number.NaN, 15)).toBe(0)
  })
})

describe('buildSkuDisplayLines（逐 SKU 行的备品）', () => {
  it('A2 单 SKU：备品 = ceil(订单数量 × 订单级率‰)', () => {
    const lines = buildSkuDisplayLines(singleSkuGroup(), 15)
    expect(lines).toHaveLength(1)
    expect(lines[0]!.spare).toBe(150)
  })

  it('A4 多 SKU：逐 SKU 取整后求和（3×1 件 @500‰ → 1+1+1=3，而非 ceil(1.5)=2）', () => {
    const lines = buildSkuDisplayLines(tinyMultiSkuGroup(), 500)
    expect(lines.slice(0, 3).map((l) => l.spare)).toEqual([1, 1, 1])
    expect(lines[3]!.isTotal).toBe(true)
    expect(lines[3]!.spare).toBe(3)
    expect(lines[3]!.qty).toBe(3)
  })

  it('A5 率为 0：各行备品均为 0（不是缺失）', () => {
    const lines = buildSkuDisplayLines(singleSkuGroup(), 0)
    expect(lines[0]!.spare).toBe(0)
  })
})

describe('A1/A3 屏幕：新列位置 + 自定义行率不影响备品', () => {
  it('表头 10 列，「备品数量」在第 4 位（订单数量右侧）', () => {
    const ths = headerTexts(mountModal(singleSkuGroup()))
    expect(ths).toEqual([
      '客户', '产品名称', '订单数量', '备品数量', '供应商',
      '布料名称', '规格型号', '损耗率', '数量', '单位',
    ])
  })

  it('备品单元格 = 150.0（订单级率 15‰），与相邻「订单数量」列同格式', () => {
    const cells = firstRowCells(mountModal(singleSkuGroup()))
    expect(cells[2]!.text()).toBe('10000.0')
    expect(cells[3]!.text()).toBe('150.0')
  })

  it('A3 自定义行率（450‰ 材料损耗）不得影响备品：仍为 150.0', () => {
    const wrapper = mountModal(singleSkuGroup(), {
      lossRate: 15,
      groupSpareRates: [15],
      // 逐行率设为材料损耗量级：只应影响「数量」列，不应影响备品
      fabricLossRates: [[[450]]],
    })
    const cells = firstRowCells(wrapper)

    expect(cells[3]!.text()).toBe('150.0')
    expect(cells[3]!.text()).not.toContain('4500')
  })

  it('A3 反向：即使逐行率被改成 0，备品也不变（仍取订单级率）', () => {
    const wrapper = mountModal(singleSkuGroup(), {
      lossRate: 15,
      groupSpareRates: [15],
      fabricLossRates: [[[0]]],
    })
    expect(firstRowCells(wrapper)[3]!.text()).toBe('150.0')
  })

  it('多分组：各分组按自己的订单级率算备品（不共用顶部值）', () => {
    const g1 = singleSkuGroup()
    const g2: FactoryGroup = { ...singleSkuGroup(), customer_name: '客户B', product_quantity: 1000, skus: undefined }
    const data: FactorySummaryData = { success: true, order_count: 2, spare_rate: 15, groups: [g1, g2] }
    const wrapper = mount(SummaryModal, {
      props: {
        open: true, factoryData: data, supplierData: { success: true, order_count: 2, materials: [] },
        editMode: false, lossRate: 15, orderCount: 2, supplierGroups: [],
        groupSpareRates: [15, 30],
      },
      global: { stubs }, attachTo: document.body,
    })

    const rows = wrapper.findAll('tbody tr')
    // g2 的率是 30‰ → ceil(1000 × 30‰) = 30
    const secondGroupSpare = rows[1]!.findAll('td')[3]!.text()
    expect(secondGroupSpare).toBe('30.0')
  })
})

describe('A1 打印 / 导出：与屏幕同源（10 列）', () => {
  it('共享表头常量含 10 列且第 4 列为「备品数量」', () => {
    const doc = new DOMParser().parseFromString(`<table><thead>${FACTORY_TABLE_HEAD}</thead></table>`, 'text/html')
    const headers = [...doc.querySelectorAll('th')].map((th) => th.textContent || '')
    expect(headers).toHaveLength(10)
    expect(headers[3]).toBe('备品数量')
    expect(headers[7]).toBe('损耗率')
  })

  it('数据行第 4 列 = 备品（订单级率），第 8 列 = 数量（材料损耗率加放）、第 9 列 = 单位', () => {
    // 两种率显式分离：订单级率 15‰ 只喂备品；逐行材料损耗率 450‰ 只喂「数量」列
    const html = buildFactoryHtml(dataWith(singleSkuGroup(), 15), 15, [[[450]]])
    const doc = new DOMParser().parseFromString(`<table><tbody>${html}</tbody></table>`, 'text/html')
    const cells = [...doc.querySelectorAll('tbody tr:first-child td')].map((td) => td.textContent || '')

    expect(cells[3]).toBe('150.0') // 备品 = ceil(10000 × 15‰)
    // 数量按该行材料损耗率 450‰ 加放：890 × 1.45 = 1290.5 → ceil 1291
    expect(cells[8]).toBe('1291')
    expect(cells[9]).toBe('码')
  })

  it('分组级率优先于传入的统一率（打印与屏幕同口径）', () => {
    const html = buildFactoryHtml(dataWith(singleSkuGroup(), 15), 15, undefined, [30])
    const doc = new DOMParser().parseFromString(`<table><tbody>${html}</tbody></table>`, 'text/html')
    const cells = [...doc.querySelectorAll('tbody tr:first-child td')].map((td) => td.textContent || '')
    expect(cells[3]).toBe('300.0')
  })
})
