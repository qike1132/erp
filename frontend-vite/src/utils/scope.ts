/**
 * 物料计算器的「作用域」标识与展示名（作用域 = 产品 × 角色）。
 *
 * 作用域唯一键 `p|<product_id>|r|<role_id|default>` 是跨模块约定，
 * 桌面端结果列与移动端作用域卡片共用。
 *
 * 原属 `roleMatrix.ts`；跨角色对比矩阵于 2026-10-07 整体移除后，
 * 这里只保留仍被复用的两个纯函数与默认标签常量。
 */
import type { MaterialCalcScopeGroup } from '@/api/purchase'

/** 默认 BOM 作用域的展示名（role_id 为 null 时）。 */
export const DEFAULT_BOM_LABEL = '默认BOM'

/** 作用域 key 生成（跨模块唯一约定）。 */
export function scopeKeyOf(group: Pick<MaterialCalcScopeGroup, 'product_id' | 'role_id'>): string {
  const rolePart = group.role_id == null ? 'default' : String(group.role_id)
  return `p|${group.product_id}|r|${rolePart}`
}

/** 作用域展示名：默认 BOM → `默认BOM`；角色名缺失 → `角色#<id>`。 */
export function scopeNameOf(group: Pick<MaterialCalcScopeGroup, 'role_id' | 'role_name'>): string {
  const name = (group.role_name ?? '').trim()
  if (group.role_id == null) return name || DEFAULT_BOM_LABEL
  return name || `角色#${group.role_id}`
}
