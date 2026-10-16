/**
 * 批次号排序键。
 *
 * 批次号格式：0464(固定码) + 年 + 年内第几天 + 序号，共 10 位定长数字串。
 * 字典序即时序序（生产时间正序）。空批次排到最后，非数字段按字符串兜底，
 * 避免脏数据让整列排序失效（localeCompare 遇 null/空会让排序乱序）。
 */
export function batchSortKey(v: unknown): string {
  const s = String(v ?? '').trim()
  if (!s) return '￿' // 全角波浪号 > 任何数字字符 → 空值永远排最后
  return /^\d+$/.test(s) ? s : `￿${s}`
}

/** 批次号升序比较器（生产时间正序）。 */
export function compareBatchNo(a: unknown, b: unknown): number {
  return batchSortKey(a).localeCompare(batchSortKey(b))
}
