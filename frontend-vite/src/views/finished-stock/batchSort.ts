/**
 * 批次号排序键。
 *
 * 批次号格式：0464(固定码) + 年 + 年内第几天 + 序号，共 10 位定长数字串。
 * 字典序即时序序（生产时间正序）。
 *
 * 用可见前缀分三段，不用不可见哨兵字符：U+FFFF 这类不可见码位在 localeCompare
 * 里的 collation 权重是实现定义的（可能被当可忽略字符），「空值排最后」不成立。
 *   '0' + 数字串 → 正常批次，按原字典序
 *   '1' + 原值   → 脏数据（非纯数字），排正常批次之后
 *   '2'          → 空批次，永远最后
 */
export function batchSortKey(v: unknown): string {
  const s = String(v ?? '').trim()
  if (!s) return '2'
  return /^\d+$/.test(s) ? `0${s}` : `1${s}`
}

/** 批次号升序比较器（生产时间正序）。 */
export function compareBatchNo(a: unknown, b: unknown): number {
  return batchSortKey(a).localeCompare(batchSortKey(b))
}
