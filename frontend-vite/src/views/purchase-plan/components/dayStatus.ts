// 排产日历的状态判定与月历铺格 —— 纯函数，无 Vue 依赖，便于单测。
// 从 PurchasePlanDailyTab.vue 抽出：原来状态判定埋在组件里、铺格逻辑不存在
// （卡片列表按「有排产的日期」直出），改成月历后两者都需要独立可测。
import type { Row } from './types'

export const DAY_MS = 86400000

/** 状态样式类 + 展示文案；当天无状态标记时为 null */
export type DayMark = { cls: 'st-r' | 'st-a' | 'st-g'; lbl: string } | null

/**
 * 距今天的天数差。
 * 两边都对齐到本地零点：否则下午 3 点看列表时，当天会被算成已过期的负差。
 */
export function daysFromToday(dateStr: string, todayMs: number): number {
  return Math.round((new Date(dateStr + 'T00:00:00').getTime() - todayMs) / DAY_MS)
}

/** 今天的本地零点时间戳 */
export function startOfToday(now: Date = new Date()): number {
  const d = new Date(now)
  d.setHours(0, 0, 0, 0)
  return d.getTime()
}

/** 今天对应的 ISO 日期串（本地时区），用于月历的「今天」标记 */
export function todayIso(now: Date = new Date()): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${p(now.getMonth() + 1)}-${p(now.getDate())}`
}

/**
 * 单日状态标记。判定顺序即优先级：
 * 已全部生产 → 完成；无待完成条数 → 不标记；过期 → 延期；当天 → 今日；≤3 天 → 临期。
 */
export function dayMarkFor(
  row: Pick<Row, 'date' | '_producedPct' | '_pendingCount'>,
  todayMs: number,
): DayMark {
  if (row._producedPct === 100) return { cls: 'st-g', lbl: '✓ 完成' }
  if (row._pendingCount <= 0) return null
  const diff = daysFromToday(row.date, todayMs)
  if (diff < 0) return { cls: 'st-r', lbl: '延期 ' + Math.abs(diff) + '天' }
  if (diff === 0) return { cls: 'st-r', lbl: '今日出货' }
  if (diff <= 3) return { cls: 'st-a', lbl: '临期 ' + diff + '天' }
  return null
}

/** 月历格子：空格子（当月无排产）的 date/day/row 均为 null */
export interface MonthCell<T> {
  /** v-for key：空格子用 `blank-N`，有日期的用 ISO 日期 */
  key: string
  date: string | null
  /** 日号；空格子为 null */
  day: number | null
  row: T | null
}

/**
 * 把「有排产的日期」铺进周一起始的 7 列月历。
 * 返回长度必为 7 的整数倍（5 行或 6 行），首尾用空格子补齐；
 * 空格子代表当月没有排产的日子 —— 它本身就是要展示的信息，不是缺失。
 */
export function buildMonthCells<T extends { date: string }>(
  year: number,
  month: number,
  rows: T[],
): MonthCell<T>[] {
  // getDay() 以周日为 0，+6 %7 换算成「周一为 0」的偏移
  const lead = (new Date(year, month - 1, 1).getDay() + 6) % 7
  const daysInMonth = new Date(year, month, 0).getDate()
  const total = Math.ceil((lead + daysInMonth) / 7) * 7

  const byDate = new Map<string, T>()
  for (const r of rows) {
    // 后端已按日期聚合；万一重复，保留首行而非被末行静默覆盖
    if (!byDate.has(r.date)) byDate.set(r.date, r)
  }

  const mm = String(month).padStart(2, '0')
  const cells: MonthCell<T>[] = []
  for (let i = 0; i < total; i++) {
    const day = i - lead + 1
    if (day < 1 || day > daysInMonth) {
      cells.push({ key: `blank-${i}`, date: null, day: null, row: null })
      continue
    }
    const date = `${year}-${mm}-${String(day).padStart(2, '0')}`
    cells.push({ key: date, date, day, row: byDate.get(date) ?? null })
  }
  return cells
}
