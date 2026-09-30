/**
 * 工厂页签「按 SKU 展开物料明细」渲染测试（2026-09-30）。
 *
 * 锁定：
 *   P1 每个 SKU 一块：块内物料行独立，供应商在块内合并；
 *   P2 左侧三列（产品名称/订单数量/备品数量）按 SKU 各一行；
 *   P3 **同物料跨 SKU 联动**：同一物料在两块里的损耗率输入显示同值（同一坐标）；
 *   P4 落库明细里没有的物料 → 该行**只读**（无输入框）；
 *   P5 数据不足（旧后端 / 无 materials）→ 回退现状形态（逐 SKU 名堆叠 + 订单级物料）。
 */
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'

vi.mock('@/api', () => ({
  purchaseApi: {
    orders: vi.fn(), unprocessedOrders: vi.fn(), factorySummary: vi.fn(),
    supplierSummary: vi.fn(), saveFactoryEdits: vi.fn(), supplierSummaryExport: vi.fn(),
  },
}))

import SummaryFactoryTab from '@/views/purchase/components/SummaryFactoryTab.vue'
import type { FactoryGroup, FactorySummaryData } from '@/views/purchase/composables/useSummaryModal'

const stubs = { FontAwesomeIcon: true }

function group(): FactoryGroup {
  return {
    customer_name: '客户甲', product_name: '产品A、产品B', product_quantity: 300, spare_rate: 10,
    skus: [
      { product_name: '产品A', product_barcode: 'bA', order_qty: 100, materials: [
        { supplier_name: '供应商甲', material_name: '共享布', specification: 'S1', unit: '米', quantity: 20 },
        { supplier_name: '供应商甲', material_name: 'A专有布', specification: 'S2', unit: '米', quantity: 20 },
      ] },
      { product_name: '产品B', product_barcode: 'bB', order_qty: 200, materials: [
        { supplier_name: '供应商甲', material_name: '共享布', specification: 'S1', unit: '米', quantity: 40 },
        { supplier_name: '供应商甲', material_name: 'B专有布', specification: 'S3', unit: '米', quantity: 40 },
        { supplier_name: '供应商甲', material_name: '新加布', specification: 'S9', unit: '米', quantity: 5 },
      ] },
    ],
    suppliers: [{
      supplier_name: '供应商甲',
      fabrics: [
        { fabric_name: '共享布', specification: 'S1', unit: '米', quantity: 60, item_ids: [1] },
        { fabric_name: 'A专有布', specification: 'S2', unit: '米', quantity: 20, item_ids: [2] },
        { fabric_name: 'B专有布', specification: 'S3', unit: '米', quantity: 40, item_ids: [3] },
      ],
    }],
  }
}

function dataOf(g: FactoryGroup): FactorySummaryData {
  return { success: true, order_count: 1, spare_rate: 10, groups: [g] }
}

function mountTab(g: FactoryGroup, opts: { editMode?: boolean } = {}) {
  return mount(SummaryFactoryTab, {
    props: {
      factoryData: dataOf(g), editMode: opts.editMode ?? false, lossRate: 10, orderCount: 1,
      groupSpareRates: [10],
      fabricLossRates: [[[5, 0], [0, 0, 0]]],  // [供应商][布料]：共享布 5‰、A/B专有 0、新加布 0
    },
    global: { stubs },
  })
}

const bodyRows = (w: ReturnType<typeof mountTab>) => w.findAll('tbody tr')

describe('P1/P2 按 SKU 分块', () => {
  it('P1 共 5 个数据行（A 块 2 + B 块 3）；供应商单元格在每块内合并', () => {
    const rows = bodyRows(mountTab(group()))
    expect(rows).toHaveLength(5)
    // 每块第一行含供应商单元格，块内第二/三行不再有
    expect(rows[0]!.text()).toContain('供应商甲')
    expect(rows[1]!.text()).not.toContain('供应商甲')
    expect(rows[2]!.text()).toContain('供应商甲')
  })

  it('P2 产品名称 / 订单数量 / 备品数量 各块一行，值为该 SKU 自己的', () => {
    const rows = bodyRows(mountTab(group()))
    // 首块（A）是整组第一行 → 客户单元格在这里（rowspan = 整组行数，spec §「客户列跨整组合并」）
    expect(rows[0]!.findAll('td')[0]!.text()).toBe('客户甲')
    expect(rows[0]!.findAll('td')[1]!.text()).toBe('产品A')
    expect(rows[0]!.findAll('td')[2]!.text()).toBe('100.0')
    expect(rows[0]!.findAll('td')[3]!.text()).toBe('1.0')
    // B 块的块首行：客户列已被整组 rowspan 覆盖 → 左起第 1 格即「产品名称」
    expect(rows[2]!.findAll('td')[0]!.text()).toBe('产品B')
    expect(rows[2]!.findAll('td')[1]!.text()).toBe('200.0')
    expect(rows[2]!.findAll('td')[2]!.text()).toBe('2.0')
  })
})

describe('P3 同物料跨 SKU 联动', () => {
  it('共享布在两块里的损耗率输入显示同一个值（同一坐标）', () => {
    const rows = bodyRows(mountTab(group()))
    const rateA = rows[0]!.find('input[type="number"]')
    const rateB = rows[2]!.find('input[type="number"]')
    expect((rateA.element as HTMLInputElement).value).toBe('5')
    expect((rateB.element as HTMLInputElement).value).toBe('5')
  })
})

describe('P4 只读行', () => {
  it('落库明细里没有的「新加布」不渲染损耗率输入框，并给出说明', () => {
    const rows = bodyRows(mountTab(group()))
    const newRow = rows[4]!
    expect(newRow.text()).toContain('新加布')
    expect(newRow.find('input[type="number"]').exists()).toBe(false)
    // 必须有可解释的提示（title 或文案），否则用户不知道为什么改不了
    expect(newRow.html()).toContain('title')
  })
})

describe('P5 数据不足回退现状', () => {
  it('无 materials → 退回「逐 SKU 名堆叠 + 订单级物料」的旧形态', () => {
    const g = group()
    g.skus = [
      { product_name: '产品A', product_barcode: 'bA', order_qty: 100 },
      { product_name: '产品B', product_barcode: 'bB', order_qty: 200 },
    ]
    const rows = bodyRows(mountTab(g))

    expect(rows).toHaveLength(3)                       // 订单级 3 条落库物料
    expect(rows[0]!.text()).toContain('产品A')          // 名称仍逐 SKU 堆叠在一格
    expect(rows[0]!.text()).toContain('产品B')
    expect(rows[0]!.text()).toContain('合计')
  })
})

describe('P6 编辑态提示（跨 SKU 共用同一行明细）', () => {
  it('共享布的数量输入带「共用」提示；仅单个 SKU 出现的 A专有布不带', () => {
    const rows = bodyRows(mountTab(group(), { editMode: true }))

    // 编辑态每行只有「数量」一个输入框（率列在编辑态为只读文本）
    const sharedQty = rows[0]!.find('input[type="number"]')   // A 块 · 共享布
    expect(sharedQty.attributes('title')).toContain('共用')

    const ownQty = rows[1]!.find('input[type="number"]')      // A 块 · A专有布
    expect(ownQty.attributes('title') || '').not.toContain('共用')
  })

  it('非编辑态的率输入在共享物料上带提示（改率同样跨 SKU 生效）', () => {
    const rows = bodyRows(mountTab(group()))

    expect(rows[0]!.find('input[type="number"]').attributes('title')).toContain('共用')
    expect(rows[1]!.find('input[type="number"]').attributes('title') || '').not.toContain('共用')
  })
})

describe('P7 「各明细率不一致」提示与聚焦样式不得因改造丢失', () => {
  it('回退路径（无 materials）：非编辑态渲染「不一致」+ 率输入聚焦类；编辑态不渲染', () => {
    const g = group()
    g.skus = [{ product_name: '产品A', product_barcode: 'bA', order_qty: 100 }]
    const baseProps = {
      factoryData: dataOf(g), lossRate: 10, orderCount: 1,
      groupSpareRates: [10],
      fabricLossRateMixed: [[[true, false]]],
    }

    // 非编辑态：率列是输入框，提示紧随其后（与改造前逐字一致）
    const view = mount(SummaryFactoryTab, {
      props: { ...baseProps, editMode: false },
      global: { stubs },
    })
    const viewRow = bodyRows(view)[0]!
    expect(viewRow.text()).toContain('不一致')
    expect(viewRow.find('input[type="number"]').classes().join(' ')).toContain('focus-visible:outline-2')

    // 编辑态：率列只是只读文本 ⇒ 提示不得出现（改造前 span 在 !editMode 分支内）
    const edit = mount(SummaryFactoryTab, {
      props: { ...baseProps, editMode: true },
      global: { stubs },
    })
    const editRow = bodyRows(edit)[0]!
    expect(editRow.text()).not.toContain('不一致')
    // 编辑态下数量列才是输入框，聚焦类应落在它身上
    expect(editRow.find('input[type="number"]').classes().join(' ')).toContain('focus-visible:outline-2')
  })

  it('per-SKU 路径：该物料落库行为 mixed 时，同物料在各块都显示「不一致」', () => {
    const wrapper = mount(SummaryFactoryTab, {
      props: {
        factoryData: dataOf(group()), editMode: false, lossRate: 10, orderCount: 1,
        groupSpareRates: [10],
        // 共享布 = (供应商甲, fi=0)；两块都指向同一坐标，故两块都应显示提示
        fabricLossRateMixed: [[[true, false, false]]],
      },
      global: { stubs },
    })
    expect(bodyRows(wrapper)[0]!.text()).toContain('不一致')
    expect(bodyRows(wrapper)[2]!.text()).toContain('不一致')
  })
})

describe('P8 数量差异对照块接线（仅差异时渲染）', () => {
  it('有差异（落库「共享布」65 vs 推算 20+40=60）→ 组末尾出现对照块并点名该物料', () => {
    const g = group()
    const shared = g.suppliers[0]!.fabrics[0]!
    expect(shared.fabric_name).toBe('共享布')
    shared.quantity = 65 // 落库真值手改为与各 SKU 推算之和不同

    const w = mountTab(g)
    expect(w.text()).toContain('实际下单')
    expect(w.text()).toContain('共享布')
    // 不一致的那一行有描红标记，且只有一行（A专有布/新加布均一致或只在 BOM 侧）
    expect(w.findAll('tbody [data-diff="true"]')).toHaveLength(1)
  })

  it('无差异（默认 fixture：共享布 60、A专有布 20、B专有布 40 全对得上）→ 组末尾不渲染对照块', () => {
    const w = mountTab(group())
    expect(w.text()).not.toContain('实际下单')
    expect(w.findAll('tbody [data-diff="true"]')).toHaveLength(0)
  })
})
