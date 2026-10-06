/**
 * 数量输入的统一范围校验（真相源）。
 *
 * 客户订单页与共享 components/ocr（粘贴识别）共用同一组常量与判定，
 * 避免出现规则不一致或平行实现。页面内的既有导入入口是
 * customer-order/composables/quantityRange（再导出本模块，勿在该文件新增定义）。
 *
 * 语义约定：
 *   空值 / 未输入 / 非数字  → 不算「越界」（缺失由「必填」规则单独表达，
 *                            否则用户还没开始输入就会看到红色报错，属于噪音）；
 *   已输入但超出 [MIN, MAX] → 越界（0、负数、超上限、小数越界都算）。
 */

/** 数量下限（含） */
export const QUANTITY_MIN = 1
/** 数量上限（含） */
export const QUANTITY_MAX = 9_999_999
/** 上限的展示写法（千分位），供提示文案与属性共用 */
export const QUANTITY_MAX_TEXT = '9,999,999'

/** 越界时的提示文案（多处输入框共用同一句，保证措辞一致） */
export const QUANTITY_RANGE_MESSAGE = `数量必须介于 ${QUANTITY_MIN} 到 ${QUANTITY_MAX_TEXT} 之间`

/** 是否为「已输入但越界」。传入 v-model 绑定值（可能是 number | string | null）。 */
export function isQuantityOutOfRange(value: unknown): boolean {
  if (value === null || value === undefined || value === '') return false
  const n = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(n)) return false
  return n < QUANTITY_MIN || n > QUANTITY_MAX
}

/** 供 :aria-invalid 使用（Vue 会把 undefined 渲染为不输出该属性） */
export function quantityAriaInvalid(value: unknown): 'true' | undefined {
  return isQuantityOutOfRange(value) ? 'true' : undefined
}
