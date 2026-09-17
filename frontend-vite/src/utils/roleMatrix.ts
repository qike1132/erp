/**
 * 跨角色对比矩阵 —— 纯函数。
 *
 * 把计算器响应 `groups`（按「产品 × 作用域(角色)」分块）投影为一张
 * 「物料 × 作用域」矩阵，供桌面端 / 移动端复用（见 docs/bom-multi-role/02 §3.4）。
 *
 * 硬语义（源自架构 §7 与 PRD A-6/A-7/A-8/A-11）：
 * - **合并键** = (类别, 物料名称, 规格型号, 供应商)，**不含单位**：
 *   同名 + 同规格 + 同供应商跨作用域落**同一行**；任一不同则分行。
 * - **单位一致性**：同一合并键若跨作用域出现**不同单位** → 按单位**拆行**，
 *   每行只在本单位内求和，**末列绝不跨单位相加**。
 * - **排序**：`scopeCount ↓ → total ↓ → 类别升序 → 名称/规格/供应商升序`；
 *   拆行产生的子行按 `unit` 升序紧随其父（本函数返回的即展平后的叶子行）。
 * - **可见性**：作用域 < 2 时 `visible=false`（调用方隐藏矩阵并提示）。
 *   `groups` 缺失/为空 → 返回空矩阵且不抛错（A-5）。
 *
 * 本模块为纯函数：不依赖 Vue / DOM / 网络，可直接单测。
 */
import type { MaterialCalcRow, MaterialCalcScopeGroup } from '@/api/purchase'

/** 参与矩阵对比的物料分类（包装类不展示，与计算器扁平口径一致）。 */
export type MatrixCategory = 'filling' | 'fabric' | 'accessory'

/** 默认参与矩阵的分类，顺序即类别升序排序的次序。 */
export const MATRIX_CATEGORIES: readonly MatrixCategory[] = ['filling', 'fabric', 'accessory'] as const

/** 默认 BOM 作用域的展示名（role_id 为 null 时）。 */
export const DEFAULT_BOM_LABEL = '默认BOM'

/** 一个矩阵**列**（作用域 = 产品 × 角色；`roleId=null` 表示产品级默认 BOM）。 */
export interface MatrixScope {
  /** 作用域唯一键：`p|<product_id>|r|<role_id|default>`。 */
  key: string
  productId: number
  productName: string
  roleId: number | null
  roleName: string
}

/** 一个矩阵**行**（合并键 + 单位确定后的一条叶子行）。 */
export interface MatrixRow {
  /** 行唯一键：`<合并键>|<unit>`（用于渲染 row-key，保证同物料拆行不冲突）。 */
  key: string
  /** 合并键：`<category>|<materialName>|<specification>|<supplierName>`。 */
  groupKey: string
  category: MatrixCategory
  materialName: string
  specification: string
  supplierName: string
  unit: string
  /** 作用域 key → 用量；`null` = 该作用域无此物料（不参与合计）。 */
  cells: Record<string, number | null>
  /** 出现该物料的作用域数量（排序一级键）。 */
  scopeCount: number
  /** 该合并键是否存在单位冲突（true = 本行是拆行后的子行之一）。 */
  unitConflict: boolean
  /** 本单位内跨作用域合计（**绝不跨单位相加**）。 */
  total: number
}

/** 矩阵可见性状态，供调用方决定「渲染 / 隐藏并提示」。 */
export type MatrixReason = 'ok' | 'no-data' | 'single-scope'

export interface RoleMatrixResult {
  /** 列：按 `groups` 顺序（后端已保证默认 BOM 恒首 + 其余按名升序）。 */
  scopes: MatrixScope[]
  /** 行：已按 A-8 三级排序展平。 */
  rows: MatrixRow[]
  /** `scopes.length >= 2` 时为 true。 */
  visible: boolean
  reason: MatrixReason
}

/** 作用域 key 生成（跨模块唯一约定，见架构 §7#1/#4）。 */
export function scopeKeyOf(group: Pick<MaterialCalcScopeGroup, 'product_id' | 'role_id'>): string {
  const rolePart = group.role_id == null ? 'default' : String(group.role_id)
  return `p|${group.product_id}|r|${rolePart}`
}

/** 作用域展示名：默认 BOM → `默认BOM`；角色名缺失 → `角色#<id>`（REQ-P0-05）。 */
export function scopeNameOf(group: Pick<MaterialCalcScopeGroup, 'role_id' | 'role_name'>): string {
  const name = (group.role_name ?? '').trim()
  if (group.role_id == null) return name || DEFAULT_BOM_LABEL
  return name || `角色#${group.role_id}`
}

/** 物料名称取值：优先 `material_name`，回退 `name`（两种后端口径都兼容）。 */
function materialNameOf(row: MaterialCalcRow): string {
  return ((row.material_name || row.name || '') as string).trim()
}

/** 安全数值：非有限值按 0 计。 */
function safeNumber(v: unknown): number {
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}

interface UnitBucket {
  unit: string
  /** 作用域 key → 该单位下的用量合计（同一作用域内同单位多行会先相加）。 */
  cells: Map<string, number>
}

interface MaterialBucket {
  groupKey: string
  category: MatrixCategory
  materialName: string
  specification: string
  supplierName: string
  byUnit: Map<string, UnitBucket>
}

/**
 * 把「拆行后的叶子行」按合并键聚拢、每组内按 `unit` 升序稳定排列。
 *
 * 用途：保证单位冲突被拆出的子行**相邻且按单位升序**追加（架构 §3.4）。
 * 输入行的**首次出现顺序即输出组顺序**（稳定）。
 */
export function splitByUnitConflict(rows: MatrixRow[]): MatrixRow[] {
  const order: string[] = []
  const groups = new Map<string, MatrixRow[]>()
  for (const row of rows) {
    let bucket = groups.get(row.groupKey)
    if (!bucket) {
      bucket = []
      groups.set(row.groupKey, bucket)
      order.push(row.groupKey)
    }
    bucket.push(row)
  }
  const out: MatrixRow[] = []
  for (const key of order) {
    const bucket = groups.get(key) as MatrixRow[]
    bucket.sort((a, b) => a.unit.localeCompare(b.unit))
    out.push(...bucket)
  }
  return out
}

/**
 * 由 `groups` 派生跨角色对比矩阵。
 *
 * @param groups  计算器响应的 `groups`（可能为 null/undefined/空 → 空矩阵）。
 * @param categories 参与对比的分类（默认 filling/fabric/accessory）。
 */
export function deriveRoleMatrix(
  groups: MaterialCalcScopeGroup[] | null | undefined,
  categories: readonly MatrixCategory[] = MATRIX_CATEGORIES,
): RoleMatrixResult {
  if (!Array.isArray(groups) || groups.length === 0) {
    return { scopes: [], rows: [], visible: false, reason: 'no-data' }
  }

  // ---- 1) 收集列（作用域），保持 groups 顺序（后端已定死默认 BOM 恒首） ----
  const scopes: MatrixScope[] = []
  const seenScope = new Set<string>()
  const buckets = new Map<string, MaterialBucket>()

  for (const group of groups) {
    const scopeKey = scopeKeyOf(group)
    if (!seenScope.has(scopeKey)) {
      seenScope.add(scopeKey)
      scopes.push({
        key: scopeKey,
        productId: group.product_id,
        productName: group.product_name ?? '',
        roleId: group.role_id ?? null,
        roleName: scopeNameOf(group),
      })
    }

    for (const category of categories) {
      const rows = (group[category] ?? []) as MaterialCalcRow[]
      for (const row of rows) {
        const name = materialNameOf(row)
        const spec = (row.specification ?? '').trim()
        const supplier = (row.supplier_name ?? '').trim()
        const unit = (row.unit ?? '').trim()
        // 合并键不含单位 → 单位冲突会自然落进同一 bucket
        const groupKey = `${category}|${name}|${spec}|${supplier}`

        let bucket = buckets.get(groupKey)
        if (!bucket) {
          bucket = { groupKey, category, materialName: name, specification: spec, supplierName: supplier, byUnit: new Map() }
          buckets.set(groupKey, bucket)
        }
        let unitBucket = bucket.byUnit.get(unit)
        if (!unitBucket) {
          unitBucket = { unit, cells: new Map() }
          bucket.byUnit.set(unit, unitBucket)
        }
        unitBucket.cells.set(scopeKey, (unitBucket.cells.get(scopeKey) ?? 0) + safeNumber(row.total_quantity))
      }
    }
  }

  // ---- 2) 生成叶子行（按单位拆行；每行只在本单位内合计） ----
  interface RowGroup {
    bucket: MaterialBucket
    scopeSet: Set<string>
    rankTotal: number
    rows: MatrixRow[]
  }
  const rowGroups: RowGroup[] = []

  for (const bucket of buckets.values()) {
    const units = Array.from(bucket.byUnit.keys()).sort((a, b) => a.localeCompare(b))
    const unitConflict = units.length > 1
    const scopeSet = new Set<string>()
    let rankTotal = 0
    const rows: MatrixRow[] = []

    for (const unit of units) {
      const unitBucket = bucket.byUnit.get(unit) as UnitBucket
      const cells: Record<string, number | null> = {}
      let total = 0
      let scopeCount = 0
      for (const scope of scopes) {
        const v = unitBucket.cells.get(scope.key)
        if (v == null) {
          cells[scope.key] = null
        } else {
          cells[scope.key] = v
          total += v
          scopeCount += 1
          scopeSet.add(scope.key)
        }
      }
      rankTotal += total
      rows.push({
        key: `${bucket.groupKey}|${unit}`,
        groupKey: bucket.groupKey,
        category: bucket.category,
        materialName: bucket.materialName,
        specification: bucket.specification,
        supplierName: bucket.supplierName,
        unit,
        cells,
        scopeCount,
        unitConflict,
        total,
      })
    }

    rowGroups.push({ bucket, scopeSet, rankTotal, rows })
  }

  // ---- 3) 排序：scopeCount ↓ → total ↓ → 类别/名称/规格/供应商 升序 ----
  const categoryRank = (c: MatrixCategory) => {
    const idx = categories.indexOf(c)
    return idx < 0 ? categories.length : idx
  }

  rowGroups.sort((a, b) => {
    const byScope = b.scopeSet.size - a.scopeSet.size
    if (byScope) return byScope
    const byTotal = b.rankTotal - a.rankTotal
    if (byTotal) return byTotal
    const byCat = categoryRank(a.bucket.category) - categoryRank(b.bucket.category)
    if (byCat) return byCat
    const byName = a.bucket.materialName.localeCompare(b.bucket.materialName)
    if (byName) return byName
    const bySpec = a.bucket.specification.localeCompare(b.bucket.specification)
    if (bySpec) return bySpec
    return a.bucket.supplierName.localeCompare(b.bucket.supplierName)
  })

  // ---- 4) 展平：子行按 unit 升序紧随其父 ----
  const flat: MatrixRow[] = []
  for (const group of rowGroups) flat.push(...group.rows)
  const rows = splitByUnitConflict(flat)

  const visible = scopes.length >= 2
  return { scopes, rows, visible, reason: visible ? 'ok' : 'single-scope' }
}
