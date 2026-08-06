/** 四舍五入到1位小数，避免 (1.15).toFixed(1) 之类的浮点精度问题 */
export function fmtQty(val: unknown): string {
  const n = parseFloat(String(val || 0))
  if (!isFinite(n)) return '0.0'
  return (Math.round(n * 10) / 10).toFixed(1)
}
