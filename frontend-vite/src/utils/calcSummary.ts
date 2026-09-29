/**
 * 物料计算器「汇总」视图模型 —— 纯函数。
 *
 * 把计算器响应 `groups`（按「产品 × 作用域」分块）合并为一张全产品用量表，
 * 桌面端「汇总」TAB / 移动端「汇总」卡片共用（见 mockups/material-calc-summary-2026-09-29.html 方案 A）。
 *
 * 合并口径与跨角色对比矩阵（roleMatrix.ts）一致：
 * - **合并键** = (分类, 物料名称, 规格型号, 供应商)，**不含单位**：
 *   同键跨产品落同一行、数量相加；任一不同则分行。
 * - **单位一致性**：同一合并键若跨产品出现**不同单位** → 按单位**拆行**，
 *   各行只在本单位内求和，**绝不跨单位相加**。
 * - **行序稳定**：按首次出现顺序排列。
 * - **小数安全**：求和前 `toFixed(6)` 归一，避免 0.1+0.2 的浮点尾差
 *   （0.1+0.2=0.30000000000000004 会在展示层露出 15 位小数）。
 * - 包装类（packaging）不参与汇总，与计算器展示口径一致（CALC_CATEGORY_LIST 三类）。
 *
 * sku_count 语义：贡献该行的**不同产品数**——同产品多作用域（默认 BOM + 角色）
 * 只算 1 个 SKU；meta 同理：productCount / totalQuantity 按产品去重
 * （groups 里每个作用域共用同一订单数量、不分摊，多角色块只累计一次）。
 *
 * 本模块为纯函数：不依赖 Vue / DOM / 网络，可直接单测。
 */
import type { MaterialCalcRow, MaterialCalcScopeGroup } from '@/api/purchase'

/** 参与汇总的物料分类（与 useMaterialCalculator.CALC_CATEGORY_LIST 一致）。 */
export type SummaryCategory = 'filling' | 'fabric' | 'accessory'

export const SUMMARY_CATEGORIES: readonly SummaryCategory[] = ['filling', 'fabric', 'accessory'] as const

/** 汇总行：MaterialCalcRow + 跨产品 SKU 数（用于「N 个SKU」徽标）。 */
export interface SummaryRow extends MaterialCalcRow {
  sku_count: number
}

export interface CalcSummaryResult {
  /** 各分类的合并行（0 项分类为空数组，由渲染层决定是否展示）。 */
  rows: Record<SummaryCategory, SummaryRow[]>
  /** 参与计算的产品数（按 product_id 去重）。 */
  productCount: number
  /** 全部产品订单数量合计（每产品只累计一次，多角色不分摊）。 */
  totalQuantity: number
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

/** 小数安全求和：`toFixed(6)` 归一，去掉浮点尾差再回数。 */
function addQuantity(a: number, b: number): number {
  return parseFloat((a + b).toFixed(6))
}

interface RowBucket extends SummaryRow {
  /** 所属分类（收敛时按它归位到 rows）。 */
  category: SummaryCategory
  /** 贡献过该行的 product_id 集合（去重后即 sku_count）。 */
  skuSet: Set<number>
}

/**
 * 由 `groups` 派生全产品汇总表。
 *
 * @param groups 计算器响应的 `groups`（null/undefined/空 → 空结果，不抛错）。
 */
export function deriveCalcSummary(
  groups: MaterialCalcScopeGroup[] | null | undefined,
): CalcSummaryResult {
  const rows: Record<SummaryCategory, SummaryRow[]> = { filling: [], fabric: [], accessory: [] }
  if (!Array.isArray(groups) || groups.length === 0) {
    return { rows, productCount: 0, totalQuantity: 0 }
  }

  // key = `${category}|${name}|${spec}|${supplier}|${unit}`：含单位，单位不同自然落不同桶
  const buckets = new Map<string, RowBucket>()
  const products = new Map<number, number>()

  for (const group of groups) {
    const productId = group.product_id
    // 订单数量按产品去重：groups 里同产品每个作用域共用同一 quantity、不分摊
    // （见 api/purchase.ts 契约注释），只累计首个作用域，多角色不重复相加。
    if (!products.has(productId)) products.set(productId, safeNumber(group.quantity))

    for (const category of SUMMARY_CATEGORIES) {
      const groupRows = (group[category] ?? []) as MaterialCalcRow[]
      for (const row of groupRows) {
        const name = materialNameOf(row)
        const spec = (row.specification ?? '').trim()
        const supplier = (row.supplier_name ?? '').trim()
        const unit = (row.unit ?? '').trim()
        const key = `${category}|${name}|${spec}|${supplier}|${unit}`

        let bucket = buckets.get(key)
        if (!bucket) {
          bucket = {
            category,
            supplier_name: supplier,
            material_name: name,
            name,
            material_code: (row.material_code ?? '') as string,
            specification: spec,
            unit,
            total_quantity: 0,
            sku_count: 0,
            skuSet: new Set<number>(),
          }
          buckets.set(key, bucket)
        }
        bucket.total_quantity = addQuantity(bucket.total_quantity, safeNumber(row.total_quantity))
        bucket.skuSet.add(productId)
      }
    }
  }

  // 收敛：行序 = 首次出现顺序（Map 迭代保序）
  for (const bucket of buckets.values()) {
    bucket.sku_count = bucket.skuSet.size
    const { skuSet, category, ...row } = bucket
    void skuSet
    rows[category].push(row)
  }

  return { rows, productCount: products.size, totalQuantity: parseFloat([...products.values()].reduce((s, v) => s + v, 0).toFixed(6)) }
}
