/**
 * QA 独立对抗性验证（严过关）— 损耗率「重开回显」修复。
 *
 * 本文件不复述工程师用例，只针对主理人点名的硬点独立取证：
 *  C1. 【零回归】响应不含 spare_rate（旧后端）→ lossRate=0 且 saveFactoryEdits 零调用；
 *      并对照「含字段」时不会误触自动落库（避免把回显当成用户交互）。
 *  C2. 【回显不夹带提交】openSummary(spare_rate=5) → handleCompleteOrder(999) 实参 (999, undefined)；
 *      反向对照 lossRateTouched=true → 确实夹带 5（证明接线有效、断言非恒真）。
 *  C3. 【组件层】lossRateMixed=true 渲染提示文案；false 不渲染（真实挂载 SummaryPanel）。
 *  C4. 【基线恢复】落库成功 → persistedLossRate 更新；编辑→取消编辑恢复该值（非 0）。
 *  C5. 【close 复位】四项全复位（lossRate/persistedLossRate/saveState/lossRateMixed）。
 *
 * 若任一失败 = 源码缺陷信号，须阻断放行。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'

vi.mock('@/api', () => ({
  purchaseApi: {
    orders: vi.fn(),
    unprocessedOrders: vi.fn(),
    factorySummary: vi.fn(),
    supplierSummary: vi.fn(),
    saveFactoryEdits: vi.fn(),
    supplierSummaryExport: vi.fn(),
    completeOrder: vi.fn(),
    batchComplete: vi.fn(),
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
import { usePurchaseActions } from '@/views/purchase/composables/usePurchaseActions'
import SummaryPanel from '@/views/purchase/components/SummaryPanel.vue'
import { purchaseApi } from '@/api'
import type { FactorySummaryData, SupplierSummaryData } from '@/views/purchase/composables/useSummaryModal'

const FACTORY: FactorySummaryData = {
  success: true,
  order_count: 1,
  groups: [
    {
      customer_name: '客户A',
      product_name: '产品1',
      product_quantity: 100,
      suppliers: [
        { supplier_name: '供应商1', fabrics: [{ fabric_name: '布料A', specification: 'S1', quantity: 10, unit: '米', item_ids: [101] }] },
      ],
    },
  ],
}
const SUPPLIER: SupplierSummaryData = {
  success: true,
  materials: [{ material_name: '布料A', specification: 'S1', total_quantity: 20, unit: '米', supplier_name: '供应商1' }],
}

function withExtra(extra: Record<string, unknown>): FactorySummaryData {
  return { ...FACTORY, ...extra }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(purchaseApi.factorySummary).mockResolvedValue(FACTORY as never)
  vi.mocked(purchaseApi.supplierSummary).mockResolvedValue(SUPPLIER as never)
  vi.mocked(purchaseApi.saveFactoryEdits).mockResolvedValue({ success: true } as never)
})

function buildActions(summary: ReturnType<typeof useSummaryModal>) {
  const purchaseOrders = {
    completeOrder: vi.fn().mockResolvedValue(true),
    batchComplete: vi.fn().mockResolvedValue(2),
    selectedIds: [1, 2],
  }
  const actions = usePurchaseActions({
    purchaseOrders: purchaseOrders as never,
    completed: {} as never,
    summary,
    confirm: { confirm: vi.fn().mockResolvedValue(true) } as never,
    queryClient: { invalidateQueries: vi.fn() } as never,
  })
  return { actions, purchaseOrders }
}

describe('C1. 零回归：旧后端（无字段）不产生任何写请求', () => {
  it('响应完全不含 spare_rate/spare_rate_mixed → lossRate=0/mixed=false/touched=false 且 saveFactoryEdits 零调用', async () => {
    // FACTORY 本身不含两字段（模拟未重启的旧后端）
    const m = useSummaryModal()
    await m.openSummary([7, 8])

    expect(m.lossRate).toBe(0)
    expect(m.persistedLossRate).toBe(0)
    expect(m.lossRateMixed).toBe(false)
    expect(m.lossRateTouched).toBe(false)
    expect(m.lossRateSaveState).toBe('idle')
    expect(purchaseApi.saveFactoryEdits).not.toHaveBeenCalled()
  })

  it('响应含 spare_rate=null（全无值）→ 同样落 0，且不误触自动落库', async () => {
    vi.mocked(purchaseApi.factorySummary).mockResolvedValue(withExtra({ spare_rate: null, spare_rate_mixed: false }) as never)
    const m = useSummaryModal()
    await m.openSummary([7, 8])

    expect(m.lossRate).toBe(0)
    expect(m.lossRateTouched).toBe(false)
    expect(purchaseApi.saveFactoryEdits).not.toHaveBeenCalled()
  })

  it('响应含 spare_rate=5 → 回显 5 但同样不触发任何写请求（回显≠交互）', async () => {
    vi.mocked(purchaseApi.factorySummary).mockResolvedValue(withExtra({ spare_rate: 5 }) as never)
    const m = useSummaryModal()
    await m.openSummary([7, 8])

    expect(m.lossRate).toBe(5)
    expect(m.lossRateTouched).toBe(false)
    expect(purchaseApi.saveFactoryEdits).not.toHaveBeenCalled()
  })
})

describe('C2. 回显不夹带提交', () => {
  it('openSummary(spare_rate=5) → handleCompleteOrder(999) 实参 (999, undefined)', async () => {
    vi.mocked(purchaseApi.factorySummary).mockResolvedValue(withExtra({ spare_rate: 5 }) as never)
    const m = useSummaryModal()
    await m.openSummary([7, 8])
    expect(m.lossRate).toBe(5)
    expect(m.lossRateTouched).toBe(false)

    const { actions, purchaseOrders } = buildActions(m)
    await actions.handleCompleteOrder(999)
    expect(purchaseOrders.completeOrder).toHaveBeenCalledWith(999, undefined)
  })

  it('反向对照：lossRateTouched=true（用户确实交互）→ 夹带 5（接线有效，非恒 undefined）', async () => {
    const m = useSummaryModal()
    await m.openSummary([7, 8])
    m.applyLossRate(5) // 仅本地交互，不落库
    expect(m.lossRateTouched).toBe(true)

    const { actions, purchaseOrders } = buildActions(m)
    await actions.handleCompleteOrder(999)
    expect(purchaseOrders.completeOrder).toHaveBeenCalledWith(999, 5)
  })
})

describe('C3. SummaryPanel 组件层 mixed 提示', () => {
  function mountModal(lossRateMixed: boolean, lossRate = 0) {
    return mount(SummaryPanel, {
      props: {
        factoryData: FACTORY,
        supplierData: null,
        editMode: false,
        lossRate,
        orderCount: 1,
        supplierGroups: [],
        lossRateMixed,
      },
    })
  }

  it('lossRateMixed=true → 文案「各订单损耗率不一致」可见', () => {
    const w = mountModal(true)
    expect(w.text()).toContain('各订单损耗率不一致')
    w.unmount()
  })

  it('lossRateMixed=false → 该文案不渲染', () => {
    const w = mountModal(false)
    expect(w.text()).not.toContain('各订单损耗率不一致')
    w.unmount()
  })

  it('缺省（未传 lossRateMixed）→ 不渲染（向后兼容）', () => {
    const w = mount(SummaryPanel, {
      props: { factoryData: FACTORY, supplierData: null, editMode: false, lossRate: 0, orderCount: 1, supplierGroups: [] },
    })
    expect(w.text()).not.toContain('各订单损耗率不一致')
    w.unmount()
  })
})

describe('C4. 已落库基线恢复（非 0）', () => {
  it('applyLossRateAndSave(5) 成功 → persistedLossRate=5；编辑→取消编辑 → lossRate=5', async () => {
    const m = useSummaryModal()
    await m.openSummary([7, 8])
    await m.applyLossRateAndSave(5)

    expect(m.persistedLossRate).toBe(5)
    m.toggleEditMode(true)
    m.toggleEditMode(false)
    expect(m.lossRate).toBe(5)
    expect(m.lossRateTouched).toBe(false)
    expect(m.lossRateSaveState).toBe('idle')
  })
})

describe('C5. close() 全量复位', () => {
  it('close() → lossRate=0 / persistedLossRate=0 / saveState=idle / lossRateMixed=false', async () => {
    vi.mocked(purchaseApi.factorySummary).mockResolvedValue(withExtra({ spare_rate: null, spare_rate_mixed: true }) as never)
    const m = useSummaryModal()
    await m.openSummary([7, 8])
    expect(m.lossRateMixed).toBe(true)

    await m.applyLossRateAndSave(7)
    expect(m.persistedLossRate).toBe(7)

    m.close()
    expect(m.lossRate).toBe(0)
    expect(m.persistedLossRate).toBe(0)
    expect(m.lossRateSaveState).toBe('idle')
    expect(m.lossRateMixed).toBe(false)
  })
})
