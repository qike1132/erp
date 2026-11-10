/**
 * 供应商页签「数量」必须与工厂页签「数量」列同源（2026-11-10 生产反馈）。
 *
 * 缺陷：按 SKU 展开模式下，工厂表数量列显示**逐 SKU 的 BOM 推算值**
 * （宝乐绒 200.5 × 1.03 → 207），而供应商页签取的是**落库明细**（50 × 1.03 → 52）。
 * 同一物料两页数字不一致（生产单 PO-2611-005）。
 *
 * 本测试锁定：供应商页签数量 = Σ 工厂可见行数量（同物料键跨 SKU/角色累加）。
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

vi.mock('@/composables/useToast', () => ({
  showToast: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))

vi.mock('@/composables/useExport', async () => {
  const { ref: r } = await import('vue')
  return { useExport: () => ({ exporting: r(false), runExport: vi.fn() }) }
})

import { useSummaryModal } from '@/views/purchase/composables/useSummaryModal'
import { purchaseApi } from '@/api'
import type { FactorySummaryData, SupplierSummaryData } from '@/views/purchase/composables/useSummaryModal'

/** 按 SKU 展开模式：BOM 推算 200.5、落库明细 50、订单级率 30‰。 */
const PER_SKU_FACTORY: FactorySummaryData = {
  success: true,
  order_count: 1,
  spare_rate: 30,
  groups: [
    {
      customer_name: '网易',
      product_name: '《蛋仔派对》缤果乐园系列',
      product_quantity: 30000,
      suppliers: [
        {
          supplier_name: '三虎',
          fabrics: [
            {
              fabric_name: '宝乐绒', specification: '01#', unit: '码',
              quantity: 50, item_ids: [1], loss_rate: null,
            },
          ],
        },
      ],
      skus: [
        {
          product_name: '香蕉',
          order_qty: 30000,
          materials: [
            {
              supplier_name: '三虎', material_name: '宝乐绒', specification: '01#',
              unit: '码', quantity: 200.5, part_name: '',
            },
          ],
        },
      ],
    },
  ],
}

const STORED_SUPPLIER: SupplierSummaryData = {
  success: true,
  materials: [
    {
      material_name: '宝乐绒', specification: '01#', unit: '码',
      total_quantity: 50, supplier_name: '三虎',
      orders: [{ order_no: 'PO-2611-005', quantity: 50 }],
    },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(purchaseApi.factorySummary).mockResolvedValue(PER_SKU_FACTORY as never)
  vi.mocked(purchaseApi.supplierSummary).mockResolvedValue(STORED_SUPPLIER as never)
  vi.mocked(purchaseApi.saveFactoryEdits).mockResolvedValue({ success: true } as never)
})

describe('供应商页签数量与工厂页签同源', () => {
  it('按 SKU 模式下取 BOM 推算值（207），而不是落库明细（52）', async () => {
    const m = useSummaryModal()
    await m.openSummary([1])

    expect(m.supplierGroups).toHaveLength(1)
    expect(m.supplierGroups[0]!.materials[0]!.total_quantity).toBe(207)
    // 原始后端数据（落库真值）不被写回
    expect(m.supplierData!.materials[0]!.total_quantity).toBe(50)
  })

  it('同一物料跨角色多行按工厂可见值累加（香珠 6×5000=30000）', async () => {
    const roles = [15, 16, 17, 18, 19, 20]
    const factory: FactorySummaryData = {
      success: true,
      order_count: 1,
      spare_rate: 30,
      groups: [{
        customer_name: '网易',
        product_name: '《蛋仔派对》缤果乐园系列',
        product_quantity: 30000,
        suppliers: [{
          supplier_name: '包好包',
          fabrics: [{
            fabric_name: '香珠', specification: '5g', unit: '个',
            quantity: 0, item_ids: [], loss_rate: null,
          }],
        }],
        skus: [{
          product_name: '香蕉',
          order_qty: 30000,
          materials: roles.map(() => ({
            supplier_name: '包好包', material_name: '香珠', specification: '5g',
            unit: '个', quantity: 5000, part_name: '', role_id: null,
          })),
        }],
      }],
    }
    vi.mocked(purchaseApi.factorySummary).mockResolvedValue(factory as never)
    const supplier: SupplierSummaryData = {
      success: true,
      materials: [{
        material_name: '香珠', specification: '5g', unit: '个',
        total_quantity: 30000, supplier_name: '包好包',
      }],
    }
    vi.mocked(purchaseApi.supplierSummary).mockResolvedValue(supplier as never)

    const m = useSummaryModal()
    await m.openSummary([1])

    // 香珠无落库坐标 → 不加损耗；6 行各 5000，合计 30000
    expect(m.supplierGroups[0]!.materials[0]!.total_quantity).toBe(30000)
  })
})
