/**
 * 分批出货计划校验规则（2026-10-06 v2）
 *
 * 口径（用户裁决）：各批数量之和必须排满订单数量。
 * 与 quantityRange 同模式：集中规则与文案，表单/编辑弹窗/提交拦截共用，
 * 避免「缺项」与「值错误」两类提示互相混入。
 */
import type { ShipmentPlanSplit } from './types'

/** 各批数量之和（数量非法按 0 计，由 planSplitsMessage 单独报错） */
export function sumSplitQuantity(plans: ShipmentPlanSplit[]): number {
  return plans.reduce((s, p) => s + (Number(p.quantity) > 0 ? Math.floor(Number(p.quantity)) : 0), 0)
}

/**
 * 分批计划校验：返回 '' 表示合法，否则返回违规原因文案（可直接展示）。
 * 空数组视为「无计划」，恒合法。
 */
export function planSplitsMessage(plans: ShipmentPlanSplit[], orderQuantity: number): string {
  if (!plans.length) return ''
  for (const p of plans) {
    if (!p.date) return '存在未选择出货日期的批次'
    // 与后端 int 口径一致：非整数（如 1.5）也会被 Pydantic 422 拒绝，提前拦下
    if (!(Number.isInteger(Number(p.quantity)) && Number(p.quantity) >= 1)) return '分批数量必须为大于 0 的整数'
  }
  const total = sumSplitQuantity(plans)
  if (total > orderQuantity) return `分批数量之和(${total})超出订单数量(${orderQuantity})`
  if (total < orderQuantity) return `分批数量之和(${total})未排满订单数量(${orderQuantity})，还差 ${orderQuantity - total}`
  return ''
}
