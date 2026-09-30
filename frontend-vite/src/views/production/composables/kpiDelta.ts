/**
 * KPI 环比文案。
 *
 * 分母为 0（昨天没生产 / 刚上线无数据）时返回破折号 —— 这是刻意的：
 * 直接算会得到 Infinity% 或 NaN%，显示在界面上比"没有对比"更糟。
 */
export interface DeltaText {
  text: string
  tone: 'up' | 'down' | 'flat'
}

export function formatDelta(current: number, previous: number): DeltaText {
  if (!Number.isFinite(current) || !Number.isFinite(previous) || previous === 0) {
    return { text: '—', tone: 'flat' }
  }
  const pct = ((current - previous) / previous) * 100
  if (Math.abs(pct) < 0.05) return { text: '0.0%', tone: 'flat' }
  const sign = pct > 0 ? '+' : '-'
  return { text: `${sign}${Math.abs(pct).toFixed(1)}%`, tone: pct > 0 ? 'up' : 'down' }
}

/** 生产天数：当月有产量的天数（后端 daily_data 逐日给出，含 0 的天） */
export function countProductionDays(days: Array<{ total: { quantity: number } }> | undefined): number {
  if (!days?.length) return 0
  return days.filter((d) => d.total.quantity > 0).length
}

/** 日均产量 = 当月累计 ÷ 生产天数；生产天数为 0 时返回 0（不是 NaN） */
export function dailyAverage(totalQuantity: number, productionDays: number): number {
  if (!productionDays) return 0
  return totalQuantity / productionDays
}
