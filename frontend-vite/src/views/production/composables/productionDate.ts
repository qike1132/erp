/**
 * 生产页共用的日期工具。
 *
 * 刻意单独成文件：趋势区间与明细筛选都要用"本地日期字符串"与"本周一"，
 * 两处各写一份必然漂移 —— 尤其"本地日期"这条：用 toISOString 会按 UTC 切日，
 * 东八区晚上 8 点之后会算成前一天。
 */
/** 本地日期字符串（不要用 toISOString） */
export function toLocalDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** 近 N 日区间：今天往前推 N-1 天到今天（闭区间，天然可跨月） */
export function trendRange(days: number, today = new Date()): { start_date: string; end_date: string } {
  const end = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  const start = new Date(end)
  start.setDate(start.getDate() - (days - 1))
  return { start_date: toLocalDate(start), end_date: toLocalDate(end) }
}

/** 本周一（以周一为一周之始） */
export function mondayOf(d: Date): Date {
  const day = d.getDay() // 0=周日
  const diff = day === 0 ? 6 : day - 1
  const monday = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  monday.setDate(monday.getDate() - diff)
  return monday
}
