/**
 * 按 SKU 行模型（perSkuRows）单测（2026-09-30）。
 *
 * 锁定：
 *   R1 每个 SKU 一块：skuIdx / skuRowSpan / supplierRowSpan 正确；
 *   R2 每行映射回落库坐标 (si, fi) 与 itemIds —— 这是「同物料率/数量联动」的实现基础；
 *   R3 落库明细里没有的物料 → coord=null（只读行，不得写库）；
 *   R4 差异判定：|Σ推算 − 落库| ≤ 0.005 不算差异（浮点尾差不得误报）；
 *   R5 无 materials（旧后端 / 无 BOM）→ 返回 []，调用方据此回退现状。
 */
import { describe, it, expect } from 'vitest'
import { buildPerSkuRows, computeQuantityDiff, materialKeyOf, buildStoredRows } from '@/views/purchase/composables/perSkuRows'
import type { FactoryGroup } from '@/views/purchase/composables/useSummaryModal'

/** 2 SKU × 同供应商；共享布跨 SKU 各算各的；另有一条「只出现在 BOM、落库里没有」的新物料 */
function twoSkuGroup(): FactoryGroup {
  return {
    customer_name: '客户甲',
    product_name: '产品A、产品B',
    product_quantity: 300,
    spare_rate: 10,
    skus: [
      {
        product_name: '产品A', product_barcode: 'bA', order_qty: 100,
        materials: [
          { supplier_name: '供应商甲', material_name: '共享布', specification: 'S1', unit: '米', quantity: 20 },
          { supplier_name: '供应商甲', material_name: 'A专有布', specification: 'S2', unit: '米', quantity: 20 },
        ],
      },
      {
        product_name: '产品B', product_barcode: 'bB', order_qty: 200,
        materials: [
          { supplier_name: '供应商甲', material_name: '共享布', specification: 'S1', unit: '米', quantity: 40 },
          { supplier_name: '供应商甲', material_name: 'B专有布', specification: 'S3', unit: '米', quantity: 40 },
          { supplier_name: '供应商甲', material_name: '新加布', specification: 'S9', unit: '米', quantity: 5 },
        ],
      },
    ],
    suppliers: [
      {
        supplier_name: '供应商甲',
        fabrics: [
          { fabric_name: '共享布', specification: 'S1', unit: '米', quantity: 60, item_ids: [1] },
          { fabric_name: 'A专有布', specification: 'S2', unit: '米', quantity: 20, item_ids: [2] },
          { fabric_name: 'B专有布', specification: 'S3', unit: '米', quantity: 40, item_ids: [3] },
        ],
      },
    ],
  }
}

describe('materialKeyOf', () => {
  it('与 summaryMaterialKey 同口径：供应商+物料名+规格+单位', () => {
    expect(materialKeyOf({ supplier_name: '甲', material_name: '布', specification: 'S1', unit: '米' }))
      .toBe(materialKeyOf({ supplier_name: '甲', material_name: '布', specification: 'S1', unit: '米' }))
    expect(materialKeyOf({ supplier_name: '甲', material_name: '布' }))
      .not.toBe(materialKeyOf({ supplier_name: '乙', material_name: '布' }))
  })
})

describe('buildPerSkuRows', () => {
  it('R1 每 SKU 一块：块内行数 = 该 SKU 的物料数；供应商在块内合并', () => {
    const rows = buildPerSkuRows(twoSkuGroup(), 10)

    expect(rows).toHaveLength(5) // A 2 行 + B 3 行
    expect(rows.filter((r) => r.isFirstSkuRow).map((r) => r.skuIdx)).toEqual([0, 1])
    expect(rows[0]!.skuRowSpan).toBe(2)
    expect(rows[2]!.skuRowSpan).toBe(3)
    // 供应商在 A 块 2 行合并、B 块 3 行合并
    expect(rows[0]!.isFirstSupplierRow).toBe(true)
    expect(rows[0]!.supplierRowSpan).toBe(2)
    expect(rows[2]!.supplierRowSpan).toBe(3)
    expect(rows[1]!.isFirstSupplierRow).toBe(false)
  })

  it('R1 左侧三列文本行：per-SKU 模式恒 1 行，数量取该 SKU 的 order_qty、备品按订单级率算', () => {
    const rows = buildPerSkuRows(twoSkuGroup(), 10)

    expect(rows[0]!.cellLines).toEqual([{ name: '产品A', qty: 100, spare: 1, isTotal: false }])
    expect(rows[2]!.cellLines).toEqual([{ name: '产品B', qty: 200, spare: 2, isTotal: false }])
  })

  it('R2 每行映射回落库坐标与 itemIds（共享布在两个 SKU 块里指向同一坐标 → 联动天然成立）', () => {
    const rows = buildPerSkuRows(twoSkuGroup(), 10)

    expect(rows[0]!.coord).toEqual({ si: 0, fi: 0 })   // A 块 · 共享布
    expect(rows[2]!.coord).toEqual({ si: 0, fi: 0 })   // B 块 · 共享布 → 同一坐标
    expect(rows[0]!.itemIds).toEqual([1])
    expect(rows[1]!.itemIds).toEqual([2])
    expect(rows[3]!.itemIds).toEqual([3])
  })

  it('R3 落库明细里没有的物料 → coord=null、itemIds 为空（只读行）', () => {
    const rows = buildPerSkuRows(twoSkuGroup(), 10)
    const newFabric = rows.find((r) => r.materialName === '新加布')!

    expect(newFabric.coord).toBeNull()
    expect(newFabric.itemIds).toEqual([])
  })

  it('R5 无 materials（旧后端 / 无 BOM）→ 返回空数组，调用方回退现状', () => {
    const group = twoSkuGroup()
    group.skus = [{ product_name: '产品A', product_barcode: 'bA', order_qty: 100 }]

    expect(buildPerSkuRows(group, 10)).toEqual([])
  })

  it('R6 个别 SKU 无 BOM → 保留块结构并产出占位行（不隐藏该 SKU）', () => {
    const group = twoSkuGroup()
    group.skus![1]!.materials = []

    const rows = buildPerSkuRows(group, 10)

    const placeholder = rows.find((r) => r.noBom)
    expect(placeholder).toBeDefined()
    expect(placeholder!.skuIdx).toBe(1)
    expect(placeholder!.cellLines[0]!.name).toBe('产品B')
    // 占位行没有可写目标
    expect(placeholder!.coord).toBeNull()
    expect(placeholder!.itemIds).toEqual([])
  })
})

describe('computeQuantityDiff', () => {
  it('R4 一致时不报差异（含浮点尾差 ≤0.005）', () => {
    const group = twoSkuGroup()
    // 让「新加布」也出现在落库明细里，且数值完全一致
    group.suppliers![0]!.fabrics.push({ fabric_name: '新加布', specification: 'S9', unit: '米', quantity: 5, item_ids: [9] })
    const rows = buildPerSkuRows(group, 10)

    expect(computeQuantityDiff(group, rows)).toEqual([])
  })

  it('R4 尾差 ≤0.005 不报；超过才报（并给出推算值与落库值）', () => {
    const group = twoSkuGroup()
    group.suppliers![0]!.fabrics[0]!.quantity = 60.004 // Σ推算 60 → 差 0.004，不报
    expect(computeQuantityDiff(group, buildPerSkuRows(group, 10))).toEqual([])

    group.suppliers![0]!.fabrics[0]!.quantity = 65 // 差 5 → 报
    expect(computeQuantityDiff(group, buildPerSkuRows(group, 10))).toEqual([
      { materialName: '共享布', perSku: 60, stored: 65 },
    ])
  })

  it('R7 只在采购明细、不在任何 SKU BOM 中的物料 → 也是差异（Σ推算=0 vs 落库>0）', () => {
    const group = twoSkuGroup()
    group.suppliers![0]!.fabrics.push({
      fabric_name: '手工加料', specification: 'S8', unit: '米', quantity: 12, item_ids: [8],
    })

    expect(computeQuantityDiff(group, buildPerSkuRows(group, 10))).toEqual([
      { materialName: '手工加料', perSku: 0, stored: 12 },
    ])
  })
})

describe('buildStoredRows（屏幕与打印共用的落库行模型）', () => {
  /** 2 供应商：甲 2 条（首条带快照率）、乙 1 条；用于校验分段、快照优先、加放派生。 */
  function multiSupplierGroup(): FactoryGroup {
    return {
      customer_name: '客户甲', product_name: '产品A', product_quantity: 100,
      suppliers: [
        { supplier_name: '供应商甲', fabrics: [
          { fabric_name: '布甲A', specification: 'S1', unit: '米', quantity: 50, loss_rate: 500 },
          { fabric_name: '布甲B', specification: 'S2', unit: '米', quantity: 20 },
        ] },
        { supplier_name: '供应商乙', fabrics: [
          { fabric_name: '布乙A', specification: 'S3', unit: '卷', quantity: 10 },
        ] },
      ],
    }
  }

  it('R8 按供应商分段：段首标记与段跨度正确', () => {
    const rows = buildStoredRows(multiSupplierGroup(), () => 10)

    expect(rows.map((r) => r.supplierName)).toEqual(['供应商甲', '供应商甲', '供应商乙'])
    expect(rows.map((r) => r.isSupplierFirst)).toEqual([true, false, true])
    expect(rows.map((r) => r.supplierSpan)).toEqual([2, 2, 1])
    expect(rows.map((r) => r.specification)).toEqual(['S1', 'S2', 'S3'])
    expect(rows.map((r) => r.unit)).toEqual(['米', '米', '卷'])
  })

  it('R9 率取该行快照率（f.loss_rate）优先，缺省才回退 rateOf(si, fi)', () => {
    const rows = buildStoredRows(multiSupplierGroup(), (si, fi) => 100 * (si + 1) + fi)

    // 甲A 有快照 500 → 用 500（无视 rateOf）；甲B 无快照 → 101；乙A 无快照 → 200
    expect(rows.map((r) => r.rate)).toEqual([500, 101, 200])
  })

  it('R10 数量是「按该率加放后向上取整」的派生值（与主表同源）', () => {
    const rows = buildStoredRows(multiSupplierGroup(), () => 10)

    // 50 @500‰ → ceil(75)=75；20 @10‰ → ceil(20.2)=21；10 @10‰ → ceil(10.1)=11
    expect(rows.map((r) => r.displayQuantity)).toEqual([75, 21, 11])
  })
})
