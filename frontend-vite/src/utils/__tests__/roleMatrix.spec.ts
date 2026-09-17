import { describe, it, expect } from 'vitest'
import {
  deriveRoleMatrix,
  splitByUnitConflict,
  scopeKeyOf,
  scopeNameOf,
  DEFAULT_BOM_LABEL,
  type MatrixRow,
} from '../roleMatrix'
import type { MaterialCalcRow, MaterialCalcScopeGroup } from '@/api/purchase'

/**
 * 取出数组第 i 项。
 *
 * `tsconfig` 开启了 `noUncheckedIndexedAccess`，因此 `arr[i]` 的静态类型为
 * `T | undefined`，直接取属性会触发 TS2532。此助手在越界时立即抛错（而非用 `!`
 * 断言压过去），既修正类型，也让「预期存在」这一前提在运行时被真正校验。
 */
function at<T>(arr: readonly T[], i: number): T {
  const v = arr[i]
  if (v === undefined) {
    throw new Error(`期望索引 ${i} 存在，实际数组长度 ${arr.length}`)
  }
  return v
}

/** 构造一条物料结果行。 */
function mkRow(name: string, over: Partial<MaterialCalcRow> = {}): MaterialCalcRow {
  return {
    name,
    material_name: name,
    material_code: '',
    specification: '',
    total_quantity: 1,
    unit: '个',
    supplier_name: '供应商A',
    ...over,
  }
}

/** 构造一个作用域分组（默认 BOM：role_id=null）。 */
function mkGroup(over: Partial<MaterialCalcScopeGroup> = {}): MaterialCalcScopeGroup {
  return {
    product_id: 1,
    product_name: '产品1',
    role_id: null,
    role_name: '默认BOM',
    quantity: 10,
    filling: [],
    fabric: [],
    accessory: [],
    packaging: [],
    ...over,
  }
}

const SCOPE_DEFAULT = scopeKeyOf({ product_id: 1, role_id: null }) // p|1|r|default
const SCOPE_A = scopeKeyOf({ product_id: 1, role_id: 101 }) // p|1|r|101

describe('deriveRoleMatrix · 空态与回退 (A-5 / A-11)', () => {
  it('groups 为 undefined/null → 空矩阵，reason=no-data', () => {
    for (const input of [undefined, null]) {
      const res = deriveRoleMatrix(input)
      expect(res.rows).toEqual([])
      expect(res.scopes).toEqual([])
      expect(res.visible).toBe(false)
      expect(res.reason).toBe('no-data')
    }
  })

  it('groups 为空数组 → 空矩阵，reason=no-data', () => {
    const res = deriveRoleMatrix([])
    expect(res.rows).toEqual([])
    expect(res.visible).toBe(false)
    expect(res.reason).toBe('no-data')
  })

  it('单作用域 → visible=false 且 reason=single-scope（调用方隐藏矩阵并提示）', () => {
    const res = deriveRoleMatrix([mkGroup({ fabric: [mkRow('面料X', { unit: '码' })] })])
    expect(res.scopes).toHaveLength(1)
    expect(res.visible).toBe(false)
    expect(res.reason).toBe('single-scope')
    // 行仍被计算（调用方可选择展示分块卡）
    expect(res.rows).toHaveLength(1)
  })
})

describe('deriveRoleMatrix · 合并 / 分行 (A-6)', () => {
  it('同名 + 同规格 + 同供应商 跨角色 → 落同一行（cells 两列都有值）', () => {
    const res = deriveRoleMatrix([
      mkGroup({ role_id: null, fabric: [mkRow('共用料', { specification: 'S1', unit: '码', total_quantity: 100 })] }),
      mkGroup({ role_id: 101, role_name: '角色A', fabric: [mkRow('共用料', { specification: 'S1', unit: '码', total_quantity: 50 })] }),
    ])
    expect(res.visible).toBe(true)
    const hit = res.rows.filter((r) => r.materialName === '共用料')
    expect(hit).toHaveLength(1)
    expect(at(hit, 0).cells[SCOPE_DEFAULT]).toBe(100)
    expect(at(hit, 0).cells[SCOPE_A]).toBe(50)
    expect(at(hit, 0).scopeCount).toBe(2)
    expect(at(hit, 0).total).toBe(150)
  })

  it('同名同供应商但**规格不同** → 必须分行（不得合并成一行）', () => {
    const res = deriveRoleMatrix([
      mkGroup({
        role_id: null,
        fabric: [
          mkRow('料Z', { specification: 'S1', unit: '码', total_quantity: 10 }),
          mkRow('料Z', { specification: 'S2', unit: '码', total_quantity: 20 }),
        ],
      }),
      mkGroup({ role_id: 101, role_name: '角色A', fabric: [mkRow('料Z', { specification: 'S1', unit: '码', total_quantity: 1 })] }),
    ])
    const hit = res.rows.filter((r) => r.materialName === '料Z')
    expect(hit).toHaveLength(2) // S1 / S2 分行，绝不合并
    const s1 = hit.find((r) => r.specification === 'S1')
    const s2 = hit.find((r) => r.specification === 'S2')
    expect(s1?.total).toBe(11)
    expect(s2?.total).toBe(20)
  })

  it('同名同规格但**供应商不同** → 必须分行', () => {
    const res = deriveRoleMatrix([
      mkGroup({
        role_id: null,
        fabric: [
          mkRow('料Y', { specification: 'S1', supplier_name: '甲', unit: '码', total_quantity: 1 }),
          mkRow('料Y', { specification: 'S1', supplier_name: '乙', unit: '码', total_quantity: 2 }),
        ],
      }),
      mkGroup({ role_id: 101, role_name: '角色A', fabric: [mkRow('料Y', { specification: 'S1', supplier_name: '甲', unit: '码', total_quantity: 9 })] }),
    ])
    const hit = res.rows.filter((r) => r.materialName === '料Y')
    expect(hit).toHaveLength(2)
    expect(hit.find((r) => r.supplierName === '甲')?.total).toBe(10)
    expect(hit.find((r) => r.supplierName === '乙')?.total).toBe(2)
  })
})

describe('deriveRoleMatrix · 单位冲突拆行 (A-7)', () => {
  it('同物料跨作用域单位不一致 → 按单位拆行，且末列绝不跨单位相加', () => {
    const res = deriveRoleMatrix([
      mkGroup({ role_id: null, fabric: [mkRow('混料', { specification: 'S1', unit: '克', total_quantity: 1000 })] }),
      mkGroup({ role_id: 101, role_name: '角色A', fabric: [mkRow('混料', { specification: 'S1', unit: '个', total_quantity: 5 })] }),
    ])
    const hit = res.rows.filter((r) => r.materialName === '混料')
    expect(hit).toHaveLength(2) // 克 / 个 各一行
    expect(hit.every((r) => r.unitConflict)).toBe(true)
    const gram = hit.find((r) => r.unit === '克')
    const piece = hit.find((r) => r.unit === '个')
    expect(gram?.total).toBe(1000)
    expect(piece?.total).toBe(5)
    // 关键：不允许出现 1005 这种跨单位相加
    expect(res.rows.some((r) => r.total === 1005)).toBe(false)
  })

  it('同物料同单位跨作用域 → 合并一行且允许相加（同单位安全）', () => {
    const res = deriveRoleMatrix([
      mkGroup({ role_id: null, fabric: [mkRow('同单位料', { unit: '码', total_quantity: 3 })] }),
      mkGroup({ role_id: 101, role_name: '角色A', fabric: [mkRow('同单位料', { unit: '码', total_quantity: 4 })] }),
    ])
    const hit = res.rows.filter((r) => r.materialName === '同单位料')
    expect(hit).toHaveLength(1)
    expect(at(hit, 0).unitConflict).toBe(false)
    expect(at(hit, 0).total).toBe(7)
  })
})

describe('deriveRoleMatrix · 排序 (A-8)', () => {
  it('scopeCount ↓ → total ↓ → 类别/名称升序', () => {
    const res = deriveRoleMatrix([
      mkGroup({
        role_id: null,
        fabric: [mkRow('共用料', { specification: 'S1', total_quantity: 100 }), mkRow('独有料', { specification: 'S2', total_quantity: 5 })],
      }),
      mkGroup({ role_id: 101, role_name: '角色A', fabric: [mkRow('共用料', { specification: 'S1', total_quantity: 50 }), mkRow('少料', { specification: 'S3', total_quantity: 1 })] }),
    ])
    const names = res.rows.map((r) => r.materialName)
    // 共用料 scopeCount=2 必居首；独有料(total5) 先于 少料(total1)
    expect(names).toEqual(['共用料', '独有料', '少料'])
    expect(at(res.rows, 0).scopeCount).toBe(2)
    expect(at(res.rows, 1).scopeCount).toBe(1)
    expect(at(res.rows, 2).scopeCount).toBe(1)
  })

  it('类别升序作为最末一级：scopeCount/total 相同时按 filling→fabric→accessory', () => {
    const res = deriveRoleMatrix([
      mkGroup({
        role_id: null,
        accessory: [mkRow('配件', { unit: '个', total_quantity: 2 })],
        fabric: [mkRow('面料', { unit: '码', total_quantity: 2 })],
        filling: [mkRow('填充', { unit: '克', total_quantity: 2 })],
      }),
      mkGroup({ role_id: 101, role_name: '角色A', fabric: [mkRow('无关料', { unit: '码', total_quantity: 1 })] }),
    ])
    const cats = res.rows.filter((r) => ['填充', '面料', '配件'].includes(r.materialName)).map((r) => r.category)
    expect(cats).toEqual(['filling', 'fabric', 'accessory'])
  })
})

describe('deriveRoleMatrix · 作用域命名 / cells 语义', () => {
  it('默认 BOM → 默认BOM；角色名缺失 → 角色#<id>', () => {
    const res = deriveRoleMatrix([
      mkGroup({ role_id: null, role_name: '', fabric: [mkRow('X', { unit: '码' })] }),
      mkGroup({ role_id: 202, role_name: '', fabric: [mkRow('X', { unit: '码' })] }),
    ])
    const names = res.scopes.map((s) => s.roleName)
    expect(names).toEqual([DEFAULT_BOM_LABEL, '角色#202'])
  })

  it('该作用域无此物料 → cell 为 null，且不计入 scopeCount/total', () => {
    const res = deriveRoleMatrix([
      mkGroup({ role_id: null, fabric: [mkRow('仅默认', { unit: '码', total_quantity: 7 })] }),
      mkGroup({ role_id: 101, role_name: '角色A', fabric: [mkRow('仅默认', { unit: '码', total_quantity: 0 }), mkRow('其他', { unit: '码' })] }),
    ])
    // 角色A 也含「仅默认」但数量 0 → 视为该作用域有此物料（cells=0），scopeCount=2
    const row = res.rows.find((r) => r.materialName === '仅默认')
    expect(row?.cells[SCOPE_A]).toBe(0)
    expect(row?.scopeCount).toBe(2)
    // 「其他」仅角色A 有 → 默认列 null
    const other = res.rows.find((r) => r.materialName === '其他')
    expect(other?.cells[SCOPE_DEFAULT]).toBeNull()
    expect(other?.scopeCount).toBe(1)
  })

  it('packaging 分类默认不参与矩阵', () => {
    const res = deriveRoleMatrix([
      mkGroup({ role_id: null, packaging: [mkRow('包装物', { unit: '个' })] }),
      mkGroup({ role_id: 101, role_name: '角色A', packaging: [mkRow('包装物', { unit: '个' })] }),
    ])
    expect(res.rows).toHaveLength(0)
  })
})

describe('splitByUnitConflict', () => {
  it('同一合并键的子行被聚拢并按 unit 升序排列', () => {
    const rows: MatrixRow[] = [
      { key: 'k|A', groupKey: 'k', category: 'fabric', materialName: 'M', specification: '', supplierName: '', unit: '码', cells: {}, scopeCount: 1, unitConflict: true, total: 1 },
      { key: 'j|B', groupKey: 'j', category: 'fabric', materialName: 'N', specification: '', supplierName: '', unit: '个', cells: {}, scopeCount: 1, unitConflict: false, total: 1 },
      { key: 'k|Z', groupKey: 'k', category: 'fabric', materialName: 'M', specification: '', supplierName: '', unit: '克', cells: {}, scopeCount: 1, unitConflict: true, total: 1 },
    ]
    const out = splitByUnitConflict(rows)
    // k 组的两行必须相邻，且按 unit 升序（克 < 个? 用 localeCompare 稳定）
    expect(out.map((r) => r.groupKey)).toEqual(['k', 'k', 'j'])
    expect(at(out, 0).unit.localeCompare(at(out, 1).unit)).toBeLessThanOrEqual(0)
  })
})

describe('作用域辅助函数', () => {
  it('scopeKeyOf: null 角色 → default 段', () => {
    expect(scopeKeyOf({ product_id: 7, role_id: null })).toBe('p|7|r|default')
    expect(scopeKeyOf({ product_id: 7, role_id: 9 })).toBe('p|7|r|9')
  })
  it('scopeNameOf: 默认 BOM 无名 → 默认BOM', () => {
    expect(scopeNameOf({ role_id: null, role_name: '  ' })).toBe(DEFAULT_BOM_LABEL)
    expect(scopeNameOf({ role_id: 5, role_name: '  ' })).toBe('角色#5')
    expect(scopeNameOf({ role_id: 5, role_name: ' 爸爸 ' })).toBe('爸爸')
  })
})
