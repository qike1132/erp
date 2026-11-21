/**
 * 共享校验常量（L-16，2026-11-21 审计）：
 * 手机/联系电话正则原先在 useCustomer.ts 与 useSupplier.ts 各抄一份，
 * 提为单一真源，避免两处漂移。
 *
 * 口径：6–20 位，仅数字、-、+、空格、圆括号（座机带区号/分机也能过）。
 */
export const PHONE_RE = /^[\d\-+\s()]{6,20}$/

/** 联系电话填写了但格式不对时的统一提示文案 */
export const PHONE_INVALID_MSG = '联系电话格式不正确'
