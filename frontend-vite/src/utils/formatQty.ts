/** 四舍五入到1位小数，避免 (1.15).toFixed(1) 之类的浮点精度问题 */
import { formatNumber } from './format'

export function fmtQty(val: unknown): string {
  const n = parseFloat(String(val || 0))
  if (!isFinite(n)) return '0.0'
  return (Math.round(n * 10) / 10).toFixed(1)
}

/** L-1（2026-11-21 审计）：数量展示共享口径——有值走千分位，0 与空值留白（后端把 0 序列化成空串，不做占位符）。
 *  收编 InventoryTab.vue / ReportTable.vue 曾逐字复制的本地 fmtQty。 */
export function formatQtyBlank(v: unknown): string {
  const n = Number(v)
  return Number.isFinite(n) && n !== 0 ? formatNumber(n) : ''
}
