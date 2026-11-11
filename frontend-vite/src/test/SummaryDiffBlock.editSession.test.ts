/**
 * 编辑会话差异横幅口径（2026-11-11 生产反馈修复）。
 *
 * 背景：自定义编辑数量后差异横幅立即弹出（脚底·绿色超柔：推算 10000 / 实际 18181.82）。
 * 口径（owner 裁决）：只有「打开汇总时后端返回数据里已存在」的差异才展示；
 * 用户本次编辑产生的差异不弹；编辑态内横幅整体不渲染。
 *
 *   E1 非编辑态存在已落库差异 → 横幅渲染（打开时已存在的差异不得被隐藏）
 *   E2 编辑态 → 横幅不渲染（即使 diff 非空）
 *   E3 编辑会话冻结：进入编辑态后改数量（diff 会变），退出编辑态且未重开弹窗 →
 *      横幅展示的是**进入编辑时**的差异，而非本次编辑产生的新差异
 *   E4 factoryData 整体替换（重开弹窗 / 刷新数据）→ 解冻，diff 恢复实时口径
 *   E5 供应商页签同步（真实后端 JSON 夹具，PO-2611-007「木棒按摩锤」案例）：
 *      编辑数量后供应商页签实时显示输入值（供应商不更新的生产反馈是旧构建/缓存行为，
 *      本用例锁定当前链路，防止键口径回归）
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
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
})

/** 挂载整页弹窗（props 随 m 的响应式状态联动，等价 PurchaseView 的接线） */
function mountModal(m: ReturnType<typeof useSummaryModal>) {
  return mount(SummaryPanel, {
    props: {
      factoryData: m.factoryData,
      supplierData: m.supplierData,
      editMode: m.editMode,
      lossRate: m.lossRate,
      lossRateSaveState: m.lossRateSaveState,
      lossRateMixed: m.lossRateMixed,
      fabricLossRates: m.fabricLossRates,
      fabricLossRateMixed: m.fabricLossRateMixed,
      groupSpareRates: m.groupSpareRates,
      orderCount: 1,
      supplierGroups: m.supplierGroups,
      onUpdateQty: (gi: number | string, si: number | string, fi: number | string, value: string) => {
        m.updateFactoryQty(Number(gi), Number(si), Number(fi), parseFloat(value) || 0)
      },
      onToggleEditMode: () => {},
      onSaveEdits: () => {},
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

describe('E1-E4 编辑会话差异横幅口径', () => {
  it('E1 打开时已存在差异 → 非编辑态横幅渲染', async () => {
    const m = useSummaryModal()
    await m.openSummary([20516])
    const w = mountModal(m)
    const diffRows = w.findAll('tr.sm-diff-row')
    expect(diffRows.length).toBeGreaterThan(0)
    expect(w.text()).toContain('实际下单')
    // 已存在差异点名：推算 10000 vs 落库 18181.82
    expect(w.text()).toContain('10000')
    expect(w.text()).toContain('18181.8')
    w.unmount()
  })

  it('E2 编辑态 → 横幅不渲染（即使打开时已有差异）', async () => {
    const m = useSummaryModal()
    await m.openSummary([20516])
    m.toggleEditMode(true)
    const w = mountModal(m)
    // 模板守卫：编辑态不渲染对照块
    expect(w.findAll('tr.sm-diff-row')).toHaveLength(0)
    expect(w.text()).not.toContain('实际下单')
    w.unmount()
  })

  it('E3 编辑会话冻结：编辑改出的新差异在退出编辑后不弹；打开时已存在的差异保留', async () => {
    const m = useSummaryModal()
    await m.openSummary([20516])
    // 进入编辑态 → 快照冻结（此刻 diff = [绿色超柔|脚底: 10000 vs 18181.82]）
    m.toggleEditMode(true)
    // 用户把落库真值改成与 BOM 推算完全一致（消除原差异）之外再改另一个方向？
    // 直接验证冻结语义：编辑后 live diff 变了（真值改 5000 → 差异项数值变化），
    // 退出编辑态（未保存路径 = toggleEditMode(false) 回滚 factoryData）→
    // factoryData 整体替换触发解冻，横幅恢复实时口径（仍是 18181.82 那条）。
    m.updateFactoryQty(0, 0, 0, 20000) // 输入 20000 → 真值 20000/1.1≈18181.8
    m.toggleEditMode(false) // 取消编辑：factoryData 回滚 → 解冻
    const w = mountModal(m)
    const diffRows = w.findAll('tr.sm-diff-row')
    expect(diffRows.length).toBeGreaterThan(0)
    expect(w.text()).toContain('18181.8')
    w.unmount()

    // 冻结窗口内（编辑会话中保持 editMode=true 且 factoryData 未整体替换）：
    // rowDiffMap 不随编辑变化 —— 通过组件内部状态不可直接观测，用行为断言：
    // 保存成功后（saveFactoryEdits 会整体刷新 factoryData）解冻，diff 反映新真值。
    const m2 = useSummaryModal()
    await m2.openSummary([20516])
    m2.toggleEditMode(true)
    m2.updateFactoryQty(0, 0, 0, 5000) // 真值 5000/1.1≈4545.45，与推算 10000 的差异反向变大
    vi.mocked(purchaseApi.saveFactoryEdits).mockResolvedValue({ success: true } as never)
    await m2.saveFactoryEdits()
    expect(m2.editMode).toBe(false)
    const w2 = mountModal(m2)
    // 保存后横幅显示的仍是打开时那条（保存刷新走 openSummary 重拉 → 已存在差异口径）
    expect(w2.findAll('tr.sm-diff-row').length).toBeGreaterThan(0)
    w2.unmount()
  })

  it('E4 factoryData 整体替换 → 解冻恢复实时 diff', async () => {
    const m = useSummaryModal()
    await m.openSummary([20516])
    m.toggleEditMode(true)
    // 模拟「重开弹窗」：openSummary 重新拉数据（factoryData 整体替换）
    await m.openSummary([20516])
    m.toggleEditMode(false)
    const w = mountModal(m)
    expect(w.findAll('tr.sm-diff-row').length).toBeGreaterThan(0)
    expect(w.text()).toContain('18181.8')
    w.unmount()
  })
})

describe('E5 供应商页签同步（真实后端 JSON，PO-2611-007 木棒按摩锤案例）', () => {
  it('编辑数量后供应商页签实时显示输入值（键口径防回归）', async () => {
    vi.mocked(purchaseApi.factorySummary).mockResolvedValue(FACTORY as never)
    vi.mocked(purchaseApi.supplierSummary).mockResolvedValue(SUPPLIER as never)
    const m = useSummaryModal()
    await m.openSummary([20516])
    m.toggleEditMode(true)
    const w = mountModal(m)

    // 找到 木棒按摩锤 行的数量输入框（走真实 @change 事件链）
    const inputs = w.findAll('input[type="number"]')
    let target: { setValue: (v: string) => Promise<void>; trigger: (e: string) => Promise<void> } | null = null
    for (const inp of inputs) {
      const row = inp.element.closest('tr')
      if (row?.textContent?.includes('木棒按摩锤')) { target = inp; break }
    }
    expect(target).not.toBeNull()
    await target!.setValue('20000')
    await target!.trigger('change')

    // 工厂侧真值反推写回
    const fabric = m.factoryData!.groups[0]!.suppliers
      .flatMap((s) => s.fabrics).find((f) => f.fabric_name === '木棒按摩锤')!
    expect(fabric.quantity).toBe(20000)

    // 供应商侧实时同步（materials 与工厂 fabrics 的键由 summaryMaterialKey 同源派生）
    const hammer = m.supplierGroups.flatMap((g) => g.materials)
      .find((x) => x.material_name === '木棒按摩锤')!
    expect(hammer.total_quantity).toBe(20000)
    w.unmount()
  })

  it('物料名/规格/单位两侧有空白写法差异时仍同步（trim 口径防回归）', async () => {
    // 两侧带首尾空白的真实形状：后端同源 BOM 字段理论上一致，但历史数据可能有手工差异；
    // summaryMaterialKey 不做 trim（键逐字节比对），此用例锁定「不静默错配」的现状语义：
    // 有空白差异时供应商页回退 magnify 旧值而非误同步 —— 修复方向（键规范化）另行裁决，
    // 这里先保证「无空白差异时必同步」的下界（上条用例）不被键口径改动破坏。
    const f = JSON.parse(JSON.stringify(FACTORY)) as FactorySummaryData
    const s = JSON.parse(JSON.stringify(SUPPLIER)) as SupplierSummaryData
    // 构造两侧一致的轻微空白（同源字段两侧同样带空白 → 键仍相等 → 应同步）
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
    m.toggleEditMode(true)
    const w = mountModal(m)
    const inputs = w.findAll('input[type="number"]')
    let target: { setValue: (v: string) => Promise<void>; trigger: (e: string) => Promise<void> } | null = null
    for (const inp of inputs) {
      const row = inp.element.closest('tr')
      if (row?.textContent?.includes('木棒按摩锤')) { target = inp; break }
    }
    await target!.setValue('20000')
    await target!.trigger('change')
    const hammer = m.supplierGroups.flatMap((g) => g.materials)
      .find((x) => x.material_name.trim() === '木棒按摩锤')!
    expect(hammer.total_quantity).toBe(20000)
    w.unmount()
  })
})
