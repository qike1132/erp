/**
 * 抵扣备货数量规则（2026-10-17 审计 P1-17 / 报告内 FE-DESK-A P1-1）。
 *
 * 业务不变量只有一条：**抵扣量 ≤ min(订单数量, 可用备货)**。
 * 原先它被写成三个地方的三份临时算法：
 *   1. `useOrderForm.enableDeduct` 里 `Math.min(数量, 可用)`（只在开启那一刻算一次，之后不回收）；
 *   2. `CustomerOrderView.addStaged` 只校验「≤ 可用备货」；
 *   3. `useStagedEdit.saveEditStaged` 也只校验「≤ 可用备货」。
 * 于是「订单数量改小」或「编辑弹窗里手打超过数量的抵扣值」都能把 10 件备货扣在 3 件的订单上，
 * 后端 `process_order_deduction` 又只按 `min(请求, 可用)` 收口 → 备货被多扣且无提示。
 *
 * 现在三处共用本文件：上限用 :func:`deductLimit`，超限提示用
 * :func:`deductOverOrderMessage`，改规则只改这里。
 */

/** 数量归一：非整数取整、非正数/NaN 一律按 0（避免 NaN 或负数被写进表单/载荷） */
function toCount(value: number): number {
  const n = Math.trunc(Number(value))
  return Number.isFinite(n) && n > 0 ? n : 0
}

/**
 * 抵扣数量上限 = min(订单数量, 可用备货)。
 *
 * 订单数量是业务上限（抵扣的意思就是「这笔订单先从备货里扣出来」），
 * 可用备货是物理上限（再多也没有）。
 */
export function deductLimit(orderQuantity: number, availableStock: number): number {
  return Math.min(toCount(orderQuantity), toCount(availableStock))
}

/**
 * 「抵扣数量超过订单数量」的提示文案。
 *
 * `action` 是动作词（'添加' / '保存'），与调用点所在的操作保持一致，
 * 避免同一规则在录入页与编辑弹窗里给出互相打架的指引。
 */
export function deductOverOrderMessage(
  requested: number,
  orderQuantity: number,
  action: string,
): string {
  return `抵扣数量 ${requested} 超过订单数量 ${orderQuantity}，请调整后再${action}`
}
