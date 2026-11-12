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

// 打印预览：捕获生成的 HTML，不真的开窗口
vi.mock('@/utils/print', () => ({
  escapeHtml: (v: string) => v,
  printHtml: vi.fn(),
}))

import { useSummaryModal } from '@/views/purchase/composables/useSummaryModal'
import { purchaseApi } from '@/api'
import { printHtml } from '@/utils/print'
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
    {
      material_name: '布料A', specification: 'S1', total_quantity: 20, unit: '米', supplier_name: '供应商1',
      orders: [
        { order_no: 'PO-20261108-0001', quantity: 12 },
        { order_no: 'PO-20261108-0005', quantity: 8 },
      ],
    },
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
      {
        supplier_name: '供应商1', material_name: '布料A', specification: 'S1', unit: '米', quantity: 20,
        order_breakdown: [
          { order_no: 'PO-20261108-0001', quantity: 12 },
          { order_no: 'PO-20261108-0005', quantity: 8 },
        ],
      },
      {
        supplier_name: '供应商2', material_name: '布料C', specification: 'S3', unit: '米', quantity: 20,
        order_breakdown: [],
      },
    ])
  })

  it('统一损耗率 5‰：导出数量 = 页面派生值（工厂同源 21 + 回退 20.1）', async () => {
    const m = useSummaryModal()
    await m.openSummary([7, 8])
    m.applyLossRate(5)

    await m.exportSupplier()

    const quantities = lastExportQuantities()!
    // 逐单明细由主行合计分配而来，单独校验数量列即可（明细另有专门用例）
    expect(quantities.map((q) => ({
      supplier_name: q.supplier_name,
      material_name: q.material_name,
      specification: q.specification,
      unit: q.unit,
      quantity: q.quantity,
    }))).toEqual(
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
    expect(quantities![1]!.quantity).toBe(21)   // 回退同样向上取整：ceil(20 × 1.005) = 21
  })

  it('单行保存数量后：导出携带保存后的最新数量', async () => {
    const m = useSummaryModal()
    await m.openSummary([7, 8])
    await m.applyFabricLossRateAndSave(0, 0, 0, 100) // 该行 100‰
    m.beginQtyEdit(0, 0, 0, 22)
    m.setQtyDraft(0, 0, 0, '33')                     // 真值 30 → 展示 33
    await m.saveQtyRow(0, 0, 0)

    await m.exportSupplier()

    expect(lastExportQuantities()![0]!.quantity).toBe(33)
  })

  it('未保存的数量草稿不参与导出（供应商页只反映已落库值）', async () => {
    const m = useSummaryModal()
    await m.openSummary([7, 8])
    await m.applyFabricLossRateAndSave(0, 0, 0, 100)
    m.beginQtyEdit(0, 0, 0, 22)
    m.setQtyDraft(0, 0, 0, '33')                     // 只改草稿，不保存

    await m.exportSupplier()

    expect(lastExportQuantities()![0]!.quantity).toBe(22)
  })

  it('orderIds 为空时不发起导出请求', async () => {
    const m = useSummaryModal()
    await m.exportSupplier()

    expect(purchaseApi.supplierSummaryExport).not.toHaveBeenCalled()
  })

  it('来源订单逐单数量与主行一致：原始 8.33 导出为 9', async () => {
    const factory = {
      success: true,
      order_count: 1,
      spare_rate: 0,
      groups: [{
        customer_name: '客户', product_name: '产品', product_quantity: 1,
        suppliers: [{
          supplier_name: '供应商1',
          fabrics: [{ fabric_name: '布料X', specification: '', quantity: 8.33, unit: '码' }],
        }],
      }],
    }
    const supplier = {
      success: true,
      order_count: 1,
      materials: [{
        material_name: '布料X', specification: '', total_quantity: 8.33,
        unit: '码', supplier_name: '供应商1',
        orders: [{ order_no: 'PO-2611-003', quantity: 8.33 }],
      }],
    }
    vi.mocked(purchaseApi.factorySummary).mockResolvedValue(factory as never)
    vi.mocked(purchaseApi.supplierSummary).mockResolvedValue(supplier as never)

    const m = useSummaryModal()
    await m.openSummary([1])
    await m.exportSupplier()

    const quantities = lastExportQuantities()!
    expect(quantities[0]!.quantity).toBe(9)
    expect(quantities[0]!.order_breakdown).toEqual([
      { order_no: 'PO-2611-003', quantity: 9 },
    ])
  })
})

describe('打印预览：来源订单列', () => {
  it('表头含「来源订单」，逐单输出单号×数量；无明细显示 —', async () => {
    const m = useSummaryModal()
    await m.openSummary([7, 8])

    m.printSupplier()

    expect(printHtml).toHaveBeenCalledTimes(1)
    const html = vi.mocked(printHtml).mock.calls[0]![1] as string
    expect(html).toContain('来源订单')
    expect(html).toContain('PO-20261108-0001×12')
    expect(html).toContain('PO-20261108-0005×8')
    expect(html).toContain('—')
  })
})
