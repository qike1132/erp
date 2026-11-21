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

/**
 * 数量展示格式化：整数带千分位，小数保留至多 2 位。
 *
 * 2026-10-17 审计 AUD-14：来料数量是 float，展示层却用 toFixed(0) 四舍五入，
 * 布料 12.5 米显示 13、已到 0.4kg 显示 0，与同模块 fmtQty 口径冲突。
 * 统一到本函数，禁止再对数量直接 toFixed(0)。
 */
export function formatQuantity(value: unknown): string {
  const n = Number(value)
  if (!Number.isFinite(n)) return '0'
  // 2026-10-18 OCR 评审：整数与小数走同一 Intl 路径，保证千分位一致；
  // maximumFractionDigits 同时解决 Math.round 的二进制舍入（1.005 → 1）。
  return n.toLocaleString('en-US', { maximumFractionDigits: 2 })
}

/**
 * 生产记录数量的校验文案（L-18，2026-11-21 审计）。
 *
 * 镜像后端 schema `quantity: int, gt=0, le=999999`（schemas/daily_production.py）——
 * 小数会被 pydantic 拒收（422），前端先拦住并说人话，而不是让整批提交到一半才报错。
 * 返回空串 = 合法。
 */
export function productionQtyError(value: unknown): string {
  const n = Number(value)
  if (!Number.isInteger(n) || n <= 0) {
    return Number.isInteger(n) ? '生产数量必须大于 0' : '生产数量必须是整数'
  }
  if (n > 999_999) return '生产数量不能超过 999999'
  return ''
}
