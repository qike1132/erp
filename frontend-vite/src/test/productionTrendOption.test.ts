import { describe, expect, it } from 'vitest'

import { DEPT_COLORS, DEPT_LABELS, buildTrendOption } from '@/views/production/composables/trendChartOption'
import type { TrendDay } from '@/types'

function day(date: string, filling: number, handcraft: number, packaging: number): TrendDay {
  return { date, filling, handcraft, packaging, total: filling + handcraft + packaging }
}

describe('buildTrendOption', () => {
  it('为每个可见部门生成一条堆叠柱系列，顺序与传入的 departments 一致', () => {
    const days = [day('2026-09-01', 1, 2, 3), day('2026-09-02', 4, 5, 6)]

    const option = buildTrendOption(days, ['filling', 'handcraft', 'packaging'])
    const series = option.series as Array<Record<string, unknown>>
    const bars = series.filter((s) => s.type === 'bar')

    // 3 个可见部门 → 3 条堆叠柱，外加末尾 1 条合计折线（见下一条用例）。
    expect(series).toHaveLength(4)
    expect(bars).toHaveLength(3)
    expect(bars.map((s) => s.name)).toEqual(['充棉部', '手工部', '包装部'])
    expect(bars.every((s) => s.stack === 'dept')).toBe(true)
  })

  it('受限用户只可见一个部门时只画一条柱系列，不画三条', () => {
    // Review Focus #4：trend.departments 可能少于三个
    const days = [day('2026-09-01', 7, 0, 0)]

    const option = buildTrendOption(days, ['filling'])
    const series = option.series as Array<Record<string, unknown>>
    const bars = series.filter((s) => s.type === 'bar')

    expect(bars).toHaveLength(1)
    expect(bars[0]!.name).toBe('充棉部')
    expect(bars[0]!.data).toEqual([7])
  })

  it('x 轴用日期后两位，逐日连续', () => {
    const days = [day('2026-09-01', 1, 0, 0), day('2026-09-02', 0, 0, 0), day('2026-09-03', 5, 0, 0)]

    const option = buildTrendOption(days, ['filling', 'handcraft', 'packaging'])
    const xAxis = option.xAxis as Record<string, unknown>

    expect(xAxis.data).toEqual(['01', '02', '03'])
    expect((option.series as Array<Record<string, unknown>>)[0]!.data).toEqual([1, 0, 5])
  })

  it('合计折线始终是第四条系列，取每天的 total', () => {
    const days = [day('2026-09-01', 1, 2, 3)]

    const option = buildTrendOption(days, ['filling', 'handcraft', 'packaging'])
    const series = option.series as Array<Record<string, unknown>>
    const totalSeries = series[series.length - 1]!

    expect(totalSeries.name).toBe('合计')
    expect(totalSeries.type).toBe('line')
    expect(totalSeries.data).toEqual([6])
  })

  it('部门色与中文名来自共享常量', () => {
    expect(DEPT_LABELS.filling).toBe('充棉部')
    expect(DEPT_COLORS.packaging).toBe('#f59e0b')
  })
})
