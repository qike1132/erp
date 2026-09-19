/**
 * 汇总弹窗「损耗率回显」回归测试 —— 工程师自有护栏（对应 BUG：保存后重开回显 0）。
 *
 * 契约（与后端 get_factory_order_summary 返回的 spare_rate / spare_rate_mixed 对应）：
 *  1. openSummary 响应含 spare_rate=5 → lossRate=5 且 lossRateTouched=false（回显不算交互）；
 *  2. spare_rate=0 → lossRate=0（0 不得当成缺失），lossRateMixed=false；
 *  3. 响应不含字段（未重启的旧后端）→ lossRate=0 且不发任何请求（零回归）；
 *  4. spare_rate_mixed=true → lossRate=0 且 lossRateMixed=true；组件层提示「各订单损耗率不一致」；
 *  5. 回显不得把 lossRateTouched 置 true → handleCompleteOrder 实参 (999, undefined)；
 *  6. 自动落库成功更新 persistedLossRate；随后 编辑→取消编辑 恢复到该值（不是 0）；
 *  7. close() 全量复位。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { ref } from 'vue'

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
import { usePurchaseActions } from '@/views/purchase/composables/usePurchaseActions'
import SummaryModal from '@/views/purchase/components/SummaryModal.vue'
import { purchaseApi } from '@/api'
import type { FactorySummaryData, SupplierSummaryData } from '@/views/purchase/composables/useSummaryModal'

const SUPPLIER: SupplierSummaryData = {
  success: true,
  materials: [
    { material_name: '布料A', specification: 'S1', total_quantity: 20, unit: '米', supplier_name: '供应商1' },
  ],
}

/** 工厂汇总响应构造器：extra 用于注入 spare_rate / spare_rate_mixed（或不注入模拟旧后端）。 */
function factoryRes(extra: Partial<FactorySummaryData> = {}): FactorySummaryData {
  return {
    success: true,
    order_count: 1,
    groups: [
      {
        customer_name: '客户A',
        product_name: '产品1',
        product_quantity: 100,
        suppliers: [
          {
            supplier_name: '供应商1',
            fabrics: [{ fabric_name: '布料A', specification: 'S1', quantity: 10, unit: '米', item_ids: [101] }],
          },
        ],
      },
    ],
    ...extra,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(purchaseApi.factorySummary).mockResolvedValue(factoryRes() as never)
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
    unprocessed: {} as never,
    purchaseOrders: purchaseOrders as never,
    completed: {} as never,
    summary,
    confirm: { confirm: vi.fn().mockResolvedValue(true) } as never,
    queryClient: { invalidateQueries: vi.fn() } as never,
    isSubmitting: ref(false),
  })
  return { actions, purchaseOrders }
}

describe('openSummary 回显损耗率（服务端已落库快照）', () => {
  it('1. 响应含 spare_rate=5 → lossRate=5 且 lossRateTouched=false', async () => {
    vi.mocked(purchaseApi.factorySummary).mockResolvedValue(factoryRes({ spare_rate: 5 }) as never)
    const m = useSummaryModal()

    await m.openSummary([7, 8])

    expect(m.lossRate).toBe(5)
    expect(m.lossRateTouched).toBe(false)
    expect(m.persistedLossRate).toBe(5)
    expect(m.lossRateMixed).toBe(false)
  })

  it('2. 响应含 spare_rate=0 → lossRate=0（0 不得当成缺失），lossRateMixed=false', async () => {
    vi.mocked(purchaseApi.factorySummary).mockResolvedValue(factoryRes({ spare_rate: 0 }) as never)
    const m = useSummaryModal()

    await m.openSummary([7, 8])

    expect(m.lossRate).toBe(0)
    expect(m.persistedLossRate).toBe(0)
    expect(m.lossRateMixed).toBe(false)
  })

  it('3. 响应不含 spare_rate（旧后端）→ lossRate=0 且不发任何请求（零回归）', async () => {
    // factoryRes() 不含备用率字段 → spare_rate 为 undefined
    const m = useSummaryModal()

    await m.openSummary([7, 8])

    expect(m.lossRate).toBe(0)
    expect(m.persistedLossRate).toBe(0)
    expect(m.lossRateMixed).toBe(false)
    expect(purchaseApi.saveFactoryEdits).not.toHaveBeenCalled()
  })

  it('3b. spare_rate 为 null（全无值）→ 同样落 0，不是 NaN/undefined', async () => {
    vi.mocked(purchaseApi.factorySummary).mockResolvedValue(factoryRes({ spare_rate: null }) as never)
    const m = useSummaryModal()

    await m.openSummary([7, 8])

    expect(m.lossRate).toBe(0)
    expect(m.persistedLossRate).toBe(0)
  })

  it('4. 响应含 spare_rate_mixed=true → lossRate=0 且 lossRateMixed=true', async () => {
    vi.mocked(purchaseApi.factorySummary).mockResolvedValue(
      factoryRes({ spare_rate: null, spare_rate_mixed: true }) as never,
    )
    const m = useSummaryModal()

    await m.openSummary([7, 8])

    expect(m.lossRate).toBe(0)
    expect(m.lossRateMixed).toBe(true)
  })

  it('5. 回显不得夹带提交：openSummary(spare_rate=5) → handleCompleteOrder(999) 实参 (999, undefined)', async () => {
    vi.mocked(purchaseApi.factorySummary).mockResolvedValue(factoryRes({ spare_rate: 5 }) as never)
    const m = useSummaryModal()
    await m.openSummary([7, 8])
    // 回显把 lossRate 显示为 5，但 lossRateTouched 必须保持 false
    expect(m.lossRate).toBe(5)
    expect(m.lossRateTouched).toBe(false)

    const { actions, purchaseOrders } = buildActions(m)
    await actions.handleCompleteOrder(999)

    expect(purchaseOrders.completeOrder).toHaveBeenCalledWith(999, undefined)
  })
})

describe('persistedLossRate / 取消编辑恢复真值', () => {
  it('6. 自动落库成功 → persistedLossRate 更新；编辑→取消编辑 → lossRate 恢复为该值（非 0）', async () => {
    const m = useSummaryModal()
    await m.openSummary([7, 8])

    await m.applyLossRateAndSave(5)
    expect(m.persistedLossRate).toBe(5)

    m.toggleEditMode(true)
    // 编辑态下取消编辑：恢复到「已落库」真值 5，而不是清零
    m.toggleEditMode(false)

    expect(m.lossRate).toBe(5)
    expect(m.lossRateTouched).toBe(false)
    expect(m.lossRateSaveState).toBe('idle')
  })

  it('6b. 回显后未交互即取消编辑 → 恢复回显值（不失真）', async () => {
    vi.mocked(purchaseApi.factorySummary).mockResolvedValue(factoryRes({ spare_rate: 8 }) as never)
    const m = useSummaryModal()
    await m.openSummary([7, 8])
    expect(m.lossRate).toBe(8)

    m.toggleEditMode(true)
    m.toggleEditMode(false)

    expect(m.lossRate).toBe(8)
  })

  it('6c. 取消编辑消掉上一轮遗留的「已保存」小字（saveState → idle）', async () => {
    const m = useSummaryModal()
    await m.openSummary([7, 8])
    await m.applyLossRateAndSave(5)
    expect(m.lossRateSaveState).toBe('saved')

    m.toggleEditMode(true)
    m.toggleEditMode(false)

    expect(m.lossRateSaveState).toBe('idle')
  })

  it('7. close() 全量复位：lossRate=0、persistedLossRate=0、saveState=idle、mixed=false', async () => {
    vi.mocked(purchaseApi.factorySummary).mockResolvedValue(
      factoryRes({ spare_rate: null, spare_rate_mixed: true }) as never,
    )
    const m = useSummaryModal()
    await m.openSummary([7, 8])
    await m.applyLossRateAndSave(5)
    expect(m.lossRateMixed).toBe(false) // 落库后清掉 mixed

    m.close()

    expect(m.lossRate).toBe(0)
    expect(m.persistedLossRate).toBe(0)
    expect(m.lossRateSaveState).toBe('idle')
    expect(m.lossRateMixed).toBe(false)
  })
})

describe('SummaryModal 组件：mixed 提示', () => {
  function mountModal(lossRateMixed: boolean) {
    return mount(SummaryModal, {
      props: {
        open: true,
        factoryData: factoryRes(),
        supplierData: null,
        editMode: false,
        lossRate: 0,
        orderCount: 1,
        supplierGroups: [],
        lossRateMixed,
      },
      global: { stubs: { UiDialog: { template: '<div><slot name="title" /><slot /></div>' } } },
    })
  }

  it('lossRateMixed=true → 渲染「各订单损耗率不一致」提示', () => {
    const w = mountModal(true)
    expect(w.text()).toContain('各订单损耗率不一致')
    w.unmount()
  })

  it('lossRateMixed=false → 不渲染该提示', () => {
    const w = mountModal(false)
    expect(w.text()).not.toContain('各订单损耗率不一致')
    w.unmount()
  })
})
