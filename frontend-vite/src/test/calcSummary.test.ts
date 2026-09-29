import { describe, it, expect } from 'vitest'

import { deriveCalcSummary } from '@/utils/calcSummary'
import type { MaterialCalcRow, MaterialCalcScopeGroup } from '@/api'

/**
 * deriveCalcSummary —— 物料计算器「汇总」TAB 的合并纯函数。
 *
 * 需求：多 SKU 录入时，相同「供应商 + 物料名称 + 规格/色号」的用量合并为一行、
 * 数量相加；合并口径与跨角色对比矩阵（roleMatrix.ts）一致：
 *  · 合并键 = 分类 + 物料名 + 规格 + 供应商；单位不同 → 拆行，绝不跨单位相加；
 *  · sku_count = 贡献该行的不同产品数（同产品多角色只算 1 个）；
 *  · meta：productCount 按产品去重、totalQuantity 每个产品只累计一次订单数量
 *    （groups 里每个作用域共用同一订单数量，不分摊——见 api/purchase.ts 契约注释）。
 */

function row(over: Partial<MaterialCalcRow>): MaterialCalcRow {
  return { supplier_name: '', material_name: '', total_quantity: 0, unit: '', ...over }
}

function group(over: Partial<MaterialCalcScopeGroup>): MaterialCalcScopeGroup {
  return {
    product_id: 1,
    product_name: '招财猫盲盒毛绒挂件(混4款)',
    role_id: null,
    role_name: '默认BOM',
    quantity: 500,
    filling: [],
    fabric: [],
    accessory: [],
    packaging: [],
    ...over,
  }
}

describe('deriveCalcSummary —— 跨产品合并', () => {
  it('同分类·同名·同供应商·同规格·同单位的行合并为一行，数量相加', () => {
    const res = deriveCalcSummary([
      group({ product_id: 1, quantity: 500, filling: [row({ supplier_name: '东莞恒泰', material_name: 'PP棉', specification: '7D三维卷曲', total_quantity: 40000, unit: '克' })] }),
      group({ product_id: 2, product_name: '泰迪熊毛绒玩具(25cm)', quantity: 300, filling: [row({ supplier_name: '东莞恒泰', material_name: 'PP棉', specification: '7D三维卷曲', total_quantity: 30000, unit: '克' })] }),
    ])

    expect(res.rows.filling).toHaveLength(1)
    expect(res.rows.filling[0]!.total_quantity).toBe(70000)
    expect(res.rows.filling[0]!.sku_count).toBe(2)
  })

  it('供应商或规格任一不同则分行，不合并', () => {
    const res = deriveCalcSummary([
      group({
        product_id: 1,
        fabric: [
          row({ supplier_name: '苏州锦华', material_name: '短毛绒', specification: '110g/m²·米白', total_quantity: 125, unit: '米' }),
          row({ supplier_name: '南通凯瑞', material_name: '短毛绒', specification: '110g/m²·米白', total_quantity: 60, unit: '米' }),
          row({ supplier_name: '苏州锦华', material_name: '短毛绒', specification: '180g/m²·正红', total_quantity: 30, unit: '米' }),
        ],
      }),
      group({ product_id: 2, fabric: [row({ supplier_name: '苏州锦华', material_name: '短毛绒', specification: '110g/m²·米白', total_quantity: 105, unit: '米' })] }),
    ])

    // 规格 110g/m²·米白 + 供应商苏州锦华 → 合并；另两行因供应商/规格不同保持独立
    expect(res.rows.fabric).toHaveLength(3)
    const merged = res.rows.fabric.find((r) => r.supplier_name === '苏州锦华' && r.specification === '110g/m²·米白')
    expect(merged?.total_quantity).toBe(230)
    expect(merged?.sku_count).toBe(2)
  })

  it('同名同规格同供应商但单位不同 → 拆行各自显示，不跨单位相加', () => {
    const res = deriveCalcSummary([
      group({ product_id: 1, fabric: [row({ supplier_name: '苏州锦华', material_name: '短毛绒', specification: '110g/m²·米白', total_quantity: 100, unit: '米' })] }),
      group({ product_id: 2, fabric: [row({ supplier_name: '苏州锦华', material_name: '短毛绒', specification: '110g/m²·米白', total_quantity: 50, unit: '码' })] }),
    ])

    expect(res.rows.fabric).toHaveLength(2)
    expect(res.rows.fabric.map((r) => [r.unit, r.total_quantity])).toEqual([['米', 100], ['码', 50]])
    for (const r of res.rows.fabric) expect(r.sku_count).toBe(1)
  })

  it('同产品多角色（默认 BOM + 角色）合并时 sku_count 只算 1 个 SKU', () => {
    const res = deriveCalcSummary([
      group({ product_id: 1, quantity: 500, filling: [row({ supplier_name: '东莞恒泰', material_name: 'PP棉', specification: '7D', total_quantity: 40, unit: 'kg' })] }),
      group({ product_id: 1, role_id: 7, role_name: '打样', quantity: 500, filling: [row({ supplier_name: '东莞恒泰', material_name: 'PP棉', specification: '7D', total_quantity: 30, unit: 'kg' })] }),
    ])

    expect(res.rows.filling).toHaveLength(1)
    expect(res.rows.filling[0]!.total_quantity).toBe(70)
    expect(res.rows.filling[0]!.sku_count).toBe(1)
  })

  it('meta：productCount / totalQuantity 按产品去重，多角色不重复累计订单数量', () => {
    const res = deriveCalcSummary([
      group({ product_id: 1, quantity: 500, filling: [row({ material_name: 'PP棉', total_quantity: 40 })] }),
      group({ product_id: 1, role_id: 7, role_name: '打样', quantity: 500, filling: [row({ material_name: 'PP棉', total_quantity: 30 })] }),
      group({ product_id: 2, product_name: '泰迪熊', quantity: 300, filling: [row({ material_name: 'PP棉', total_quantity: 20 })] }),
    ])

    expect(res.productCount).toBe(2)
    expect(res.totalQuantity).toBe(800) // 500 只算一次 + 300，不是 500×2+300
  })

  it('行序稳定：按首次出现顺序排列', () => {
    const res = deriveCalcSummary([
      group({ product_id: 1, fabric: [row({ material_name: '长毛绒', specification: 'B' })] }),
      group({ product_id: 2, fabric: [row({ material_name: '短毛绒', specification: 'A' })] }),
    ])

    expect(res.rows.fabric.map((r) => r.material_name)).toEqual(['长毛绒', '短毛绒'])
  })

  it('小数用量合并不产生二进制浮点尾差（0.1 + 0.2 = 0.3）', () => {
    const res = deriveCalcSummary([
      group({ product_id: 1, fabric: [row({ material_name: '短毛绒', total_quantity: 0.1, unit: '米' })] }),
      group({ product_id: 2, fabric: [row({ material_name: '短毛绒', total_quantity: 0.2, unit: '米' })] }),
    ])

    expect(res.rows.fabric[0]!.total_quantity).toBe(0.3)
  })

  it('material_name / name 双口径与首个 material_code 透传到合并行', () => {
    const res = deriveCalcSummary([
      group({ product_id: 1, fabric: [row({ name: '短毛绒', material_name: '短毛绒', material_code: 'F-001', total_quantity: 10 })] }),
      group({ product_id: 2, fabric: [row({ material_name: '短毛绒', total_quantity: 5 })] }),
    ])

    expect(res.rows.fabric[0]!.material_name).toBe('短毛绒')
    expect(res.rows.fabric[0]!.name).toBe('短毛绒')
    expect(res.rows.fabric[0]!.material_code).toBe('F-001')
  })

  it('空输入容错：null / undefined / [] 不抛错，返回空结果', () => {
    const empty = { rows: { filling: [], fabric: [], accessory: [] }, productCount: 0, totalQuantity: 0 }

    expect(deriveCalcSummary(null)).toEqual(empty)
    expect(deriveCalcSummary(undefined)).toEqual(empty)
    expect(deriveCalcSummary([])).toEqual(empty)
  })

  it('包装类（packaging）不参与汇总，与计算器展示口径一致', () => {
    const res = deriveCalcSummary([
      group({ packaging: [row({ material_name: '彩盒', total_quantity: 500, unit: '个' })], fabric: [row({ material_name: '短毛绒', total_quantity: 10 })] }),
    ])

    expect(res.rows.fabric).toHaveLength(1)
    expect(res.rows).not.toHaveProperty('packaging')
  })
})
