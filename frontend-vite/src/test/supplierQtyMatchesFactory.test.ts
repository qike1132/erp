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
import { buildPerSkuRows, buildRowDisplayQuantities } from '@/views/purchase/composables/perSkuRows'
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
  it('落库 50 与 BOM 200.5 不一致 → 两页都取落库口径（52），不再出现 207/52 分叉', async () => {
    const m = useSummaryModal()
    await m.openSummary([1])

    // 手工调整判定（落库 50 ≠ Σ BOM 200.5）→ 工厂行以落库为准加放：ceil(50 × 1.03) = 52
    const rows = buildPerSkuRows(m.factoryData!.groups[0]!, 30)
    expect(buildRowDisplayQuantities(m.factoryData!.groups[0]!, rows, () => 30)).toEqual([52])
    // 供应商页对同一批行求和 → 52（2026-11-10 的 207/52 不一致不会回归）
    expect(m.supplierGroups[0]!.materials[0]!.total_quantity).toBe(52)
    // 原始后端数据（落库真值）不被写回
    expect(m.supplierData!.materials[0]!.total_quantity).toBe(50)
  })

  it('单行保存自定义数量后，供应商页取同一权威值（不回退 BOM 推算）', async () => {
    const m = useSummaryModal()
    await m.openSummary([1])

    // 进入编辑（预载 ceil(50 × 1.03) = 52），改成 20000 并保存
    m.beginQtyEdit(0, 0, 0, 52)
    m.setQtyDraft(0, 0, 0, '20000')
    await m.saveQtyRow(0, 0, 0)

    // 保存的是按 30‰ 反推后的落库真值（不是展示值）
    expect(purchaseApi.saveFactoryEdits).toHaveBeenCalledWith(
      [{ item_ids: [1], quantity: 19417.48 }], undefined, [1],
    )
    expect(m.qtyDrafts).toEqual({})
    // 供应商页与工厂行都按新落库值加放：ceil(19417.48 × 1.03) = 20000
    expect(m.supplierGroups[0]!.materials[0]!.total_quantity).toBe(20000)
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

describe('工厂/供应商两页数量一致性（模拟数据）', () => {
  function fabric(name: string, qty: number, extra: Record<string, unknown> = {}) {
    return {
      fabric_name: name, specification: 'S1', unit: '米', quantity: qty,
      item_ids: [1], loss_rate: null, ...extra,
    }
  }
  function skuMaterial(name: string, qty: number, supplier = '供应商1') {
    return {
      supplier_name: supplier, material_name: name, specification: 'S1',
      unit: '米', quantity: qty, part_name: '',
    }
  }

  function mockFactory(groups: unknown[]) {
    vi.mocked(purchaseApi.factorySummary).mockResolvedValue({
      success: true, order_count: 1, spare_rate: 30, groups,
    } as never)
  }
  function mockSupplier(materials: unknown[]) {
    vi.mocked(purchaseApi.supplierSummary).mockResolvedValue({
      success: true, materials,
    } as never)
  }

  it('手工调整的共享物料：以落库总量为准并按 SKU 分摊（60 vs ΣBOM 120 → 62）', async () => {
    mockFactory([{
      customer_name: '客户', product_name: '产品', product_quantity: 200,
      suppliers: [{
        supplier_name: '供应商1',
        fabrics: [fabric('共享布', 60, { item_ids: [2] }), fabric('A布', 10, { item_ids: [1] })],
      }],
      skus: [
        { product_name: 'SKU-1', order_qty: 100, materials: [skuMaterial('共享布', 60), skuMaterial('A布', 10)] },
        { product_name: 'SKU-2', order_qty: 100, materials: [skuMaterial('共享布', 60)] },
      ],
    }])
    mockSupplier([
      { material_name: '共享布', specification: 'S1', unit: '米', total_quantity: 60, supplier_name: '供应商1' },
      { material_name: 'A布', specification: 'S1', unit: '米', total_quantity: 10, supplier_name: '供应商1' },
    ])

    const m = useSummaryModal()
    await m.openSummary([1])

    const qty = Object.fromEntries(
      m.supplierGroups[0]!.materials.map((x) => [x.material_name, x.total_quantity]),
    )
    // 共享布：落库 60 ≠ ΣBOM 120 → 手工调整，总量 ceil(60×1.03)=62，
    // 分摊到两个 SKU 后相加仍为 62（不再按 BOM 逐行累加成 124）
    expect(qty['共享布']).toBe(62)
    // A布：一路 10 × 1.03 → 11
    expect(qty['A布']).toBe(11)
  })

  it('多分组（客户×产品）同物料：供应商 = 各组工厂可见行之和', async () => {
    mockFactory([
      {
        customer_name: '客户A', product_name: '产品1', product_quantity: 100,
        suppliers: [{ supplier_name: '供应商1', fabrics: [fabric('A布', 10)] }],
        skus: [{ product_name: 'SKU-A', order_qty: 100, materials: [skuMaterial('A布', 10)] }],
      },
      {
        customer_name: '客户B', product_name: '产品2', product_quantity: 200,
        suppliers: [{ supplier_name: '供应商1', fabrics: [fabric('A布', 20)] }],
        skus: [{ product_name: 'SKU-B', order_qty: 200, materials: [skuMaterial('A布', 20)] }],
      },
    ])
    mockSupplier([
      { material_name: 'A布', specification: 'S1', unit: '米', total_quantity: 30, supplier_name: '供应商1' },
    ])

    const m = useSummaryModal()
    await m.openSummary([1])

    // 10×1.03→11、20×1.03→21，合计 32（与工厂两行可见值之和一致）
    expect(m.supplierGroups[0]!.materials[0]!.total_quantity).toBe(32)
  })

  it('后台有、工厂页无对应行的物料：回退为落库量 × 统一率', async () => {
    mockFactory([{
      customer_name: '客户', product_name: '产品', product_quantity: 100,
      suppliers: [{ supplier_name: '供应商1', fabrics: [fabric('A布', 10)] }],
      skus: [{ product_name: 'SKU-A', order_qty: 100, materials: [skuMaterial('A布', 10)] }],
    }])
    mockSupplier([
      { material_name: 'A布', specification: 'S1', unit: '米', total_quantity: 10, supplier_name: '供应商1' },
      { material_name: '手工加布', specification: 'S9', unit: '米', total_quantity: 20, supplier_name: '供应商1' },
    ])

    const m = useSummaryModal()
    await m.openSummary([1])

    const qty = Object.fromEntries(
      m.supplierGroups[0]!.materials.map((x) => [x.material_name, x.total_quantity]),
    )
    expect(qty['A布']).toBe(11)
    // 回退同样向上取整（2026-11-11 口径：数量一律整数）：ceil(20 × 1.03) = 21
    expect(qty['手工加布']).toBe(21)
  })

  it('BOM 拆行数据形态：同物料跨部位两行，供应商合计仍为两行之和', async () => {
    // Task 9 扩展：BOM 把同一物料拆到两个部位（身体 2.2 / 头部 3.5），
    // 工厂页按「含部位」的物料键（materialKeyOf）逐部位展开两行；
    // 供应商页的聚合键（summaryMaterialKey 不带部位）不含部位，仍聚合为一行——
    // 合计必须等于两行可见值之和，不能按合计后单行加放。
    // 数据刻意选非整齐值以区分两种口径：逐行 ceil(2.2×1.03)=3、ceil(3.5×1.03)=4 → 7，
    // 而「先合计再取整」ceil(5.7×1.03)=6 —— 两者必须可区分。
    mockFactory([{
      customer_name: '客户', product_name: '产品', product_quantity: 100,
      suppliers: [{
        supplier_name: '供应商1',
        fabrics: [
          fabric('里布', 2.2, { item_ids: [1], part_name: '身体', part_display: '身体' }),
          fabric('里布', 3.5, { item_ids: [2], part_name: '头部', part_display: '头部' }),
        ],
      }],
      skus: [{
        product_name: 'SKU-1', order_qty: 100,
        materials: [
          {
            supplier_name: '供应商1', material_name: '里布', specification: 'S1',
            unit: '米', quantity: 2.2, part_name: '身体', part_display: '身体',
          },
          {
            supplier_name: '供应商1', material_name: '里布', specification: 'S1',
            unit: '米', quantity: 3.5, part_name: '头部', part_display: '头部',
          },
        ],
      }],
    }])
    mockSupplier([
      { material_name: '里布', specification: 'S1', unit: '米', total_quantity: 5.7, supplier_name: '供应商1' },
    ])

    const m = useSummaryModal()
    await m.openSummary([1])

    // 工厂页：同一物料按部位拆成两行（部位列分别显示，行键含部位）
    const rows = buildPerSkuRows(m.factoryData!.groups[0]!, 30)
    expect(rows).toHaveLength(2)
    expect(rows.map((r) => [r.materialName, r.partDisplay])).toEqual([
      ['里布', '身体'],
      ['里布', '头部'],
    ])

    // 供应商页：仍聚合为一行；数量 = 两条工厂可见行之和（3 + 4 = 7）
    expect(m.supplierGroups).toHaveLength(1)
    expect(m.supplierGroups[0]!.materials).toHaveLength(1)
    expect(m.supplierGroups[0]!.materials[0]!.total_quantity).toBe(7)
  })

  it('手工调整的共享明细：按落库总量分摊，不得按 6 行叠乘', async () => {
    const roles = [15, 16, 17, 18, 19, 20]
    mockFactory([{
      customer_name: '网易', product_name: '缤果系列', product_quantity: 30000,
      suppliers: [{
        supplier_name: '包好包',
        fabrics: [{
          fabric_name: '香珠', specification: '5g', unit: '个',
          quantity: 24000, item_ids: [21511], loss_rate: null,
        }],
      }],
      skus: [{
        product_name: '香蕉', order_qty: 30000,
        materials: roles.map(() => ({
          supplier_name: '包好包', material_name: '香珠', specification: '5g',
          unit: '个', quantity: 5000, part_name: '',
        })),
      }],
    }])
    mockSupplier([{
      material_name: '香珠', specification: '5g', unit: '个',
      total_quantity: 24000, supplier_name: '包好包',
    }])

    const m = useSummaryModal()
    await m.openSummary([1])

    // 落库 24000 ≠ 6×5000 → 手工调整：总量 ceil(24000×1.03)=24720，
    // 按 6 行等权分摊后相加仍为 24720；若按各行推算值累加会得到 6×5150=30900。
    expect(m.supplierGroups[0]!.materials[0]!.total_quantity).toBe(24720)
  })
})

describe('编辑态边界：BOM 有、采购明细没有的物料', () => {
  it('无落库坐标的物料不加放（与工厂表 — 口径一致）', async () => {
    const roles = [15, 16, 17, 18, 19, 20]
    vi.mocked(purchaseApi.factorySummary).mockResolvedValue({
      success: true, order_count: 1, spare_rate: 30,
      groups: [{
        customer_name: '网易', product_name: '缤果系列', product_quantity: 30000,
        suppliers: [{
          supplier_name: '包好包',
          fabrics: [{
            fabric_name: '香珠', specification: '5g', unit: '个',
            quantity: 30000, item_ids: [], loss_rate: null,
          }],
        }],
        skus: [{
          product_name: '香蕉', order_qty: 30000,
          materials: roles.map(() => ({
            supplier_name: '包好包', material_name: '香珠', specification: '5g',
            unit: '个', quantity: 5000, part_name: '',
          })),
        }],
      }],
    } as never)
    vi.mocked(purchaseApi.supplierSummary).mockResolvedValue({
      success: true,
      materials: [{
        material_name: '香珠', specification: '5g', unit: '个',
        total_quantity: 30000, supplier_name: '包好包',
      }],
    } as never)

    const m = useSummaryModal()
    await m.openSummary([1])

    // 无采购明细 → 工厂表损耗率显示「—」、数量不加放；供应商页不得自行 ×1.03
    expect(m.supplierGroups[0]!.materials[0]!.total_quantity).toBe(30000)
  })
})
