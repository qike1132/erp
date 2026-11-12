/**
 * 差异横幅口径（2026-11-11 生产反馈修复；2026-11-12 随单元格就地编辑调整）。
 *
 * 背景：自定义编辑数量后差异横幅立即弹出（脚底·绿色超柔：推算 10000 / 实际 18181.82）。
 * 口径（owner 裁决）：只有「打开汇总时后端返回数据里已存在」的差异才展示；
 * 本次会话保存产生的差异不弹；重开汇总（factoryData 整体替换）后按新数据重新快照。
 *
 *   E1 打开时已存在差异 → 横幅渲染（打开时已存在的差异不得被隐藏）
 *   E2 打开时无差异：本次会话保存产生差异 → 当前会话不弹；重开后展示
 *   E3 会话内保存不改写已冻结的快照；重开后反映新值
 *   E5 供应商页签同步（真实后端 JSON 夹具，PO-2611-007「木棒按摩锤」案例）
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'

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

vi.mock('@/composables/useToast', () => ({
  showToast: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))

vi.mock('@/composables/useExport', async () => {
  const { ref: r } = await import('vue')
  return { useExport: () => ({ exporting: r(false), runExport: vi.fn() }) }
})

import { useSummaryModal } from '@/views/purchase/composables/useSummaryModal'
import SummaryPanel from '@/views/purchase/components/SummaryPanel.vue'
import { purchaseApi } from '@/api'
import type { FactorySummaryData, SupplierSummaryData } from '@/views/purchase/composables/useSummaryModal'

const stubs = { FontAwesomeIcon: true, Transition: false, Teleport: true }

/**
 * 生产后端原样响应（PO-2611-007，get_factory/supplier_order_summary 只读导出，
 * 2026-11-11 取证时固化为本目录夹具——见 E5 供应商同步用例）。
 */
const REAL = JSON.parse(readFileSync(
  __dirname + '/fixtures/purchase-summary-po2611-007.json', 'utf-8',
))
const FACTORY = { success: true, ...REAL.factory } as FactorySummaryData
const SUPPLIER = { success: true, ...REAL.supplier } as SupplierSummaryData

/** 构造「打开时已存在差异」的最小数据：BOM 推算 10000，落库 18181.82（真实生产形状） */
const factoryWithExistingDiff = (): FactorySummaryData => ({
  success: true,
  order_count: 1,
  spare_rate: 0,
  groups: [
    {
      customer_name: '客户甲',
      product_name: '产品A',
      product_quantity: 10000,
      order_ids: [20516],
      spare_rate: 0,
      skus: [
        {
          product_name: '产品A',
          order_qty: 10000,
          materials: [
            { supplier_name: '美利达', material_name: '绿色超柔', part_name: '脚底', specification: '234', unit: '码', quantity: 10000, role_id: null },
          ],
        },
      ],
      suppliers: [
        {
          supplier_name: '美利达',
          fabrics: [
            { fabric_name: '绿色超柔', part_name: '脚底', specification: '234', unit: '码', quantity: 18181.82, item_ids: [21553], role_id: null, loss_rate: 100 },
          ],
        },
      ],
    },
  ],
})

const supplierOf = (): SupplierSummaryData => ({
  success: true,
  materials: [
    { material_name: '绿色超柔', specification: '234', total_quantity: 18181.82, unit: '码', supplier_name: '美利达' },
  ],
})

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(purchaseApi.factorySummary).mockResolvedValue(factoryWithExistingDiff() as never)
  vi.mocked(purchaseApi.supplierSummary).mockResolvedValue(supplierOf() as never)
  vi.mocked(purchaseApi.saveFactoryEdits).mockResolvedValue({ success: true } as never)
})

/** 挂载整页弹窗（props 随 m 的响应式状态联动，等价 PurchaseView 的接线） */
function mountModal(m: ReturnType<typeof useSummaryModal>) {
  return mount(SummaryPanel, {
    props: {
      factoryData: m.factoryData,
      supplierData: m.supplierData,
      lossRate: m.lossRate,
      lossRateSaveState: m.lossRateSaveState,
      lossRateMixed: m.lossRateMixed,
      fabricLossRates: m.fabricLossRates,
      fabricLossRateMixed: m.fabricLossRateMixed,
      groupSpareRates: m.groupSpareRates,
      qtyDrafts: m.qtyDrafts,
      qtySavingKey: m.qtySavingKey,
      hasUnsavedQtyEdits: m.hasUnsavedQtyEdits,
      orderCount: 1,
      supplierGroups: m.supplierGroups,
      onBeginQtyEdit: () => {},
      onQtyDraftInput: () => {},
      onCancelQtyEdit: () => {},
      onSaveQtyRow: () => {},
      onApplyLossRate: () => {},
      onApplyFabricLossRate: () => {},
      onExportFactory: () => {},
      onExportSupplier: () => {},
      onPrintFactory: () => {},
      onPrintSupplier: () => {},
      onClose: () => {},
    },
    global: { stubs },
  })
}

/** 在 factoryData 中定位某物料的落库坐标（真实夹具可能有多组/多供应商）。 */
function coordsOf(m: ReturnType<typeof useSummaryModal>, name: string, trim = false) {
  const match = (s: string | undefined) => (trim ? (s || '').trim() : (s || '')) === name
  const groups = m.factoryData!.groups || []
  for (let gi = 0; gi < groups.length; gi++) {
    const suppliers = groups[gi]!.suppliers || []
    for (let si = 0; si < suppliers.length; si++) {
      const fabrics = suppliers[si]!.fabrics || []
      for (let fi = 0; fi < fabrics.length; fi++) {
        if (match(fabrics[fi]!.fabric_name)) return { gi, si, fi, fabric: fabrics[fi]! }
      }
    }
  }
  throw new Error(`未找到物料 ${name}`)
}

describe('E1-E3 差异横幅口径', () => {
  it('E1 打开时已存在差异 → 横幅渲染并点名', async () => {
    const m = useSummaryModal()
    await m.openSummary([20516])
    const w = mountModal(m)
    const diffRows = w.findAll('tr.sm-diff-row')
    expect(diffRows.length).toBeGreaterThan(0)
    expect(w.text()).toContain('手工调整')
    // 已存在差异点名：推算 10000 vs 落库 18181.82
    expect(w.text()).toContain('10000')
    expect(w.text()).toContain('18181.8')
    w.unmount()
  })

  it('E2 打开时无差异：本次会话保存产生的差异不弹横幅，重开汇总后才展示', async () => {
    const noDiff = factoryWithExistingDiff()
    noDiff.groups[0]!.suppliers[0]!.fabrics[0]!.quantity = 10000
    vi.mocked(purchaseApi.factorySummary).mockResolvedValue(noDiff as never)

    const m = useSummaryModal()
    await m.openSummary([20516])
    expect(m.qtyDrafts).toEqual({})
    // 组件先挂载（等价真实页面：打开汇总时快照为空），随后才发生本次会话保存
    const w = mountModal(m)
    expect(w.findAll('tr.sm-diff-row')).toHaveLength(0)

    // 保存自定义数量（率 100‰：20000 → 落库真值 18181.82）
    m.beginQtyEdit(0, 0, 0, 11000)
    m.setQtyDraft(0, 0, 0, '20000')
    await m.saveQtyRow(0, 0, 0)
    await flushPromises()

    // 单行保存原地改数量、不替换 factoryData 引用 → 会话内快照不变，不弹横幅
    expect(w.findAll('tr.sm-diff-row')).toHaveLength(0)
    expect(w.text()).not.toContain('手工调整')
    w.unmount()

    // 重开汇总（后端返回落库真值已是 18181.82）→ 重新快照，横幅出现
    const after = factoryWithExistingDiff()
    vi.mocked(purchaseApi.factorySummary).mockResolvedValue(after as never)
    await m.openSummary([20516])
    const w2 = mountModal(m)
    expect(w2.findAll('tr.sm-diff-row').length).toBeGreaterThan(0)
    expect(w2.text()).toContain('18181.8')
    w2.unmount()
  })

  it('E3 会话内保存不改写已冻结的差异快照；重开后才反映新值', async () => {
    const m = useSummaryModal()
    await m.openSummary([20516])
    // 打开时快照：推算 10000 / 落库 18181.82
    const w = mountModal(m)
    expect(w.text()).toContain('18181.8')

    // 会话内再改到 30000 → 落库 27272.73，但快照仍应是打开时那条
    m.beginQtyEdit(0, 0, 0, 20000)
    m.setQtyDraft(0, 0, 0, '30000')
    await m.saveQtyRow(0, 0, 0)
    await flushPromises()

    expect(w.text()).toContain('18181.8')
    expect(w.text()).not.toContain('27272.7')
    w.unmount()

    const after = factoryWithExistingDiff()
    after.groups[0]!.suppliers[0]!.fabrics[0]!.quantity = 27272.73
    vi.mocked(purchaseApi.factorySummary).mockResolvedValue(after as never)
    await m.openSummary([20516])
    const w2 = mountModal(m)
    expect(w2.text()).toContain('27272.7')
    w2.unmount()
  })
})

describe('E5 供应商页签同步（真实后端 JSON，PO-2611-007 木棒按摩锤案例）', () => {
  it('保存数量后供应商页签显示同一权威值（键口径防回归）', async () => {
    vi.mocked(purchaseApi.factorySummary).mockResolvedValue(FACTORY as never)
    vi.mocked(purchaseApi.supplierSummary).mockResolvedValue(SUPPLIER as never)
    const m = useSummaryModal()
    await m.openSummary([20516])

    const { gi, si, fi, fabric } = coordsOf(m, '木棒按摩锤')
    m.beginQtyEdit(gi, si, fi, 0)
    m.setQtyDraft(gi, si, fi, '20000')
    await m.saveQtyRow(gi, si, fi)

    // 工厂侧真值反推写回
    expect(fabric.quantity).toBe(20000)
    // 供应商侧同源派生（materials 与工厂 fabrics 的键由 summaryMaterialKey 同源）
    const hammer = m.supplierGroups.flatMap((g) => g.materials)
      .find((x) => x.material_name === '木棒按摩锤')!
    expect(hammer.total_quantity).toBe(20000)
  })

  it('物料名/规格/单位两侧有空白写法差异时仍同步（trim 口径防回归）', async () => {
    const f = JSON.parse(JSON.stringify(FACTORY)) as FactorySummaryData
    const s = JSON.parse(JSON.stringify(SUPPLIER)) as SupplierSummaryData
    // 两侧一致的轻微空白（同源字段两侧同样带空白 → 键仍相等 → 应同步）
    for (const sup of f.groups[0]!.suppliers) {
      for (const fab of sup.fabrics) {
        if (fab.fabric_name === '木棒按摩锤') fab.fabric_name = ' 木棒按摩锤 '
      }
    }
    for (const sku of f.groups[0]!.skus || []) {
      for (const mm of sku.materials || []) {
        if (mm.material_name === '木棒按摩锤') mm.material_name = ' 木棒按摩锤 '
      }
    }
    for (const mm of s.materials) {
      if (mm.material_name === '木棒按摩锤') mm.material_name = ' 木棒按摩锤 '
    }
    vi.mocked(purchaseApi.factorySummary).mockResolvedValue(f as never)
    vi.mocked(purchaseApi.supplierSummary).mockResolvedValue(s as never)

    const m = useSummaryModal()
    await m.openSummary([20516])
    const { gi, si, fi } = coordsOf(m, '木棒按摩锤', true)
    m.beginQtyEdit(gi, si, fi, 0)
    m.setQtyDraft(gi, si, fi, '20000')
    await m.saveQtyRow(gi, si, fi)

    const hammer = m.supplierGroups.flatMap((g) => g.materials)
      .find((x) => x.material_name.trim() === '木棒按摩锤')!
    expect(hammer.total_quantity).toBe(20000)
  })
})
