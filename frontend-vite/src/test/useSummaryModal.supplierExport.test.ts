/**
 * 供应商汇总 Excel 导出 —— 「导出 = 页面所见」契约。
 *
 * 页面「供应商采购订单」的「数量」是与工厂页同源派生的展示值（含损耗率加放 / 取整），
 * 因此导出请求必须携带这份展示数量，后端据此覆盖 Excel 数量；
 * 否则后端只能沿用明细原始数量，导出与页面再次不一致（本次修复前的缺陷）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

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

import { useSummaryModal } from '@/views/purchase/composables/useSummaryModal'
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
        {
          supplier_name: '供应商1',
          fabrics: [{ fabric_name: '布料A', specification: 'S1', quantity: 20, unit: '米', item_ids: [101] }],
        },
      ],
    },
  ],
}

const SUPPLIER: SupplierSummaryData = {
  success: true,
  materials: [
    { material_name: '布料A', specification: 'S1', total_quantity: 20, unit: '米', supplier_name: '供应商1' },
    // 工厂侧无对应行 → 页面走「原始值 × 统一损耗率」回退派生
    { material_name: '布料C', specification: 'S3', total_quantity: 20, unit: '米', supplier_name: '供应商2' },
  ],
}

/** 取最近一次导出请求携带的页面展示数量行 */
function lastExportQuantities() {
  const calls = vi.mocked(purchaseApi.supplierSummaryExport).mock.calls
  return calls[calls.length - 1]![2]
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(purchaseApi.factorySummary).mockResolvedValue(FACTORY as never)
  vi.mocked(purchaseApi.supplierSummary).mockResolvedValue(SUPPLIER as never)
  vi.mocked(purchaseApi.saveFactoryEdits).mockResolvedValue({ success: true } as never)
  vi.mocked(purchaseApi.supplierSummaryExport).mockResolvedValue(undefined as never)
})

describe('导出供应商汇总 Excel：数量与页面一致', () => {
  it('未交互损耗率：导出携带页面原始数量，且带订单 ID 与供应商数', async () => {
    const m = useSummaryModal()
    await m.openSummary([7, 8])

    await m.exportSupplier()

    expect(purchaseApi.supplierSummaryExport).toHaveBeenCalledTimes(1)
    const [ids, supplierCount] = vi.mocked(purchaseApi.supplierSummaryExport).mock.calls[0]!
    expect(ids).toEqual([7, 8])
    expect(supplierCount).toBe(2)
    expect(lastExportQuantities()).toEqual([
      { supplier_name: '供应商1', material_name: '布料A', specification: 'S1', unit: '米', quantity: 20 },
      { supplier_name: '供应商2', material_name: '布料C', specification: 'S3', unit: '米', quantity: 20 },
    ])
  })

  it('统一损耗率 5‰：导出数量 = 页面派生值（工厂同源 21 + 回退 20.1）', async () => {
    const m = useSummaryModal()
    await m.openSummary([7, 8])
    m.applyLossRate(5)

    await m.exportSupplier()

    const quantities = lastExportQuantities()
    // 与供应商页签展示值逐字一致
    expect(quantities).toEqual(
      m.supplierGroups.flatMap((g) =>
        g.materials.map((mat) => ({
          supplier_name: g.supplierName,
          material_name: mat.material_name,
          specification: mat.specification || '',
          unit: mat.unit || '',
          quantity: mat.total_quantity,
        })),
      ),
    )
    expect(quantities![0]!.quantity).toBe(21)   // ceil(20 × 1.005)
    expect(quantities![1]!.quantity).toBe(20.1) // 回退：20 × 1.005
  })

  it('自定义编辑数量后（未保存）：导出携带编辑中的最新数量', async () => {
    const m = useSummaryModal()
    await m.openSummary([7, 8])
    await m.applyFabricLossRateAndSave(0, 0, 0, 100) // 该行 100‰
    m.toggleEditMode(true)
    m.updateFactoryQty(0, 0, 0, 33)                   // 真值 30 → 展示 33

    await m.exportSupplier()

    expect(lastExportQuantities()![0]!.quantity).toBe(33)
  })

  it('orderIds 为空时不发起导出请求', async () => {
    const m = useSummaryModal()
    await m.exportSupplier()

    expect(purchaseApi.supplierSummaryExport).not.toHaveBeenCalled()
  })
})
