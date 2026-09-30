/**
 * 趋势图 ECharts option 构造 —— 纯函数，不依赖 ECharts 运行时。
 *
 * 刻意不用 echarts.graphic.LinearGradient 做渐变：那会把 option 构造绑死在
 * 动态 import 的 ECharts 模块上，令本文件无法作为纯函数单测。堆叠柱用平色即可。
 *
 * 同时是部门中文名与部门色的**唯一来源**：其它组件一律从这里 import，
 * 不得各写一份（原 useProductionCharts.ts 与本文件曾各持一份部门色）。
 */
import type { TrendDay } from '@/types'

export const DEPT_LABELS: Record<string, string> = {
  filling: '充棉部',
  handcraft: '手工部',
  packaging: '包装部',
}

export const DEPT_COLORS: Record<string, string> = {
  filling: '#3b82f6',
  handcraft: '#22c55e',
  packaging: '#f59e0b',
}

const TOTAL_COLOR = '#64748b'

export function buildTrendOption(
  days: TrendDay[],
  departments: string[],
): Record<string, unknown> {
  const series = departments.map((dept) => ({
    name: DEPT_LABELS[dept] ?? dept,
    type: 'bar',
    stack: 'dept',
    barMaxWidth: 18,
    itemStyle: { color: DEPT_COLORS[dept] ?? TOTAL_COLOR },
    data: days.map((d) => (d as unknown as Record<string, number>)[dept] ?? 0),
  }))

  series.push({
    name: '合计',
    type: 'line',
    smooth: true,
    symbol: 'circle',
    symbolSize: 6,
    lineStyle: { width: 2, color: TOTAL_COLOR },
    itemStyle: { color: TOTAL_COLOR },
    data: days.map((d) => d.total),
  } as never)

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: 'rgba(255,255,255,0.96)',
      borderColor: '#e2e8f0',
      textStyle: { color: '#1e293b', fontSize: 13 },
    },
    legend: {
      bottom: 0,
      itemWidth: 12,
      itemHeight: 12,
      textStyle: { fontSize: 12, color: '#475569' },
    },
    grid: { left: 56, right: 20, top: 20, bottom: 44 },
    xAxis: {
      type: 'category',
      data: days.map((d) => d.date.slice(-2)),
      axisLabel: { fontSize: 11, color: '#94a3b8' },
      axisLine: { lineStyle: { color: '#e2e8f0' } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      name: '产量',
      axisLabel: { fontSize: 11, color: '#94a3b8' },
      splitLine: { lineStyle: { color: '#f1f5f9', type: 'dashed' } },
    },
    series,
  }
}
