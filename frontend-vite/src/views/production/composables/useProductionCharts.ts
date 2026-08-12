import { ref, watch, nextTick, onMounted, onUnmounted, type Ref, type ComputedRef } from 'vue'
import type { EChartsType } from 'echarts/core'
import type { DailySummary, MonthlySummary, DepartmentSummary, MonthlyDayData } from '@/types'

type EChartsCore = typeof import('echarts/core')

let echarts: EChartsCore | null = null
let echartsLoaded = false

async function loadEcharts(): Promise<EChartsCore> {
  if (echartsLoaded && echarts) return echarts
  const [ec, { BarChart, LineChart }, { GridComponent, TooltipComponent, TitleComponent, LegendComponent, DatasetComponent }, { CanvasRenderer }] = await Promise.all([
    import('echarts/core'),
    import('echarts/charts'),
    import('echarts/components'),
    import('echarts/renderers'),
  ])
  ec.use([
    BarChart,
    LineChart,
    GridComponent,
    TooltipComponent,
    TitleComponent,
    LegendComponent,
    DatasetComponent,
    CanvasRenderer,
  ])
  echarts = ec
  echartsLoaded = true
  return ec
}

const deptColors: Record<string, { main: string; light: string; gradient: string[] }> = {
  filling: { main: '#3b82f6', light: '#eff6ff', gradient: ['#3b82f6', '#1d4ed8'] },
  handcraft: { main: '#22c55e', light: '#f0fdf4', gradient: ['#22c55e', '#15803d'] },
  packaging: { main: '#f59e0b', light: '#fffbeb', gradient: ['#f59e0b', '#d97706'] },
}

export function useProductionCharts(
  reportSummary: ComputedRef<DailySummary | null>,
  monthlySummary: ComputedRef<MonthlySummary | null>,
  viewTab: Ref<string>,
  dailyChartRef: Ref<HTMLElement | undefined>,
  monthlyChartRef: Ref<HTMLElement | undefined>,
) {
  let dailyChart: EChartsType | null = null
  let monthlyChart: EChartsType | null = null

  function getChart(el: HTMLElement, existing: EChartsType | null): EChartsType | null {
    if (!echarts) return null
    return (existing && !existing.isDisposed()) ? existing : echarts!.init(el)
  }

  function renderDailyChart() {
    if (!echarts || !dailyChartRef.value || !reportSummary.value?.departments?.length) return
    dailyChart = getChart(dailyChartRef.value, dailyChart)
    if (!dailyChart) return
    const depts = reportSummary.value.departments
    dailyChart.setOption({
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, backgroundColor: 'rgba(255,255,255,0.96)', borderColor: '#e2e8f0', textStyle: { color: '#1e293b', fontSize: 13 } },
      grid: { left: 60, right: 20, top: 20, bottom: 30 },
      xAxis: { type: 'category', data: depts.map((d: DepartmentSummary) => d.department_label), axisLabel: { fontSize: 13, fontWeight: 600, color: '#475569' }, axisLine: { lineStyle: { color: '#e2e8f0' } }, axisTick: { show: false } },
      yAxis: [
        { type: 'value', name: '产量', axisLabel: { fontSize: 11, color: '#94a3b8' }, splitLine: { lineStyle: { color: '#f1f5f9', type: 'dashed' } } },
        { type: 'value', name: '产值', axisLabel: { fontSize: 11, color: '#94a3b8' }, splitLine: { show: false } },
      ],
      series: [
        {
          name: '产量', type: 'bar', barWidth: '30%',
          data: depts.map((d: DepartmentSummary) => ({
            value: d.total_quantity,
            itemStyle: {
              color: new echarts!.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: deptColors[d.department]?.gradient[0] ?? '#3b82f6' },
                { offset: 1, color: deptColors[d.department]?.gradient[1] ?? '#1d4ed8' },
              ]),
              borderRadius: [6, 6, 0, 0],
            },
          })),
          label: { show: true, position: 'top', fontSize: 12, fontWeight: 600, color: '#1e293b' },
        },
        {
          name: '产值', type: 'bar', barWidth: '30%', yAxisIndex: 1,
          data: depts.map((d: DepartmentSummary) => ({
            value: d.total_value,
            itemStyle: {
              color: new echarts!.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: '#fbbf24' },
                { offset: 1, color: '#f59e0b' },
              ]),
              borderRadius: [6, 6, 0, 0],
            },
          })),
          label: { show: true, position: 'top', fontSize: 11, color: '#1e293b', formatter: (p: { value: number }) => `¥${p.value}` },
        },
      ],
    }, true)
  }

  function renderMonthlyChart() {
    if (!echarts || !monthlyChartRef.value || !monthlySummary.value?.daily_data?.length) return
    monthlyChart = getChart(monthlyChartRef.value, monthlyChart)
    if (!monthlyChart) return
    const days = monthlySummary.value.daily_data.filter((d: MonthlyDayData) => d.total.quantity > 0)
    monthlyChart.setOption({
      tooltip: { trigger: 'axis', backgroundColor: 'rgba(255,255,255,0.96)', borderColor: '#e2e8f0', textStyle: { color: '#1e293b', fontSize: 13 } },
      legend: { data: ['充棉', '手工', '包装', '合计'], bottom: 0, itemWidth: 12, itemHeight: 12, textStyle: { fontSize: 12, color: '#475569' } },
      grid: { left: 50, right: 20, top: 20, bottom: 40 },
      xAxis: { type: 'category', data: days.map((d: MonthlyDayData) => d.day + '日'), axisLabel: { fontSize: 11, color: '#94a3b8' }, axisLine: { lineStyle: { color: '#e2e8f0' } }, axisTick: { show: false } },
      yAxis: { type: 'value', name: '产量', axisLabel: { fontSize: 11, color: '#94a3b8' }, splitLine: { lineStyle: { color: '#f1f5f9', type: 'dashed' } } },
      series: [
        {
          name: '充棉', type: 'bar', stack: 'dept',
          data: days.map((d: MonthlyDayData) => d.filling?.quantity ?? 0),
          itemStyle: { color: deptColors.filling!.main, borderRadius: [0, 0, 0, 0] },
        },
        {
          name: '手工', type: 'bar', stack: 'dept',
          data: days.map((d: MonthlyDayData) => d.handcraft?.quantity ?? 0),
          itemStyle: { color: deptColors.handcraft!.main },
        },
        {
          name: '包装', type: 'bar', stack: 'dept',
          data: days.map((d: MonthlyDayData) => d.packaging?.quantity ?? 0),
          itemStyle: { color: deptColors.packaging!.main, borderRadius: [4, 4, 0, 0] },
        },
        {
          name: '合计', type: 'line',
          data: days.map((d: MonthlyDayData) => d.total.quantity),
          lineStyle: { width: 2, color: '#64748b' },
          itemStyle: { color: '#64748b' },
          symbol: 'circle', symbolSize: 6,
        },
      ],
    }, true)
  }

  function initDailyChart() {
    nextTick(() => requestAnimationFrame(renderDailyChart))
  }

  function initMonthlyChart() {
    nextTick(() => requestAnimationFrame(renderMonthlyChart))
  }

  function disposeCharts() {
    dailyChart?.dispose()
    monthlyChart?.dispose()
  }

  function handleResize() {
    if (viewTab.value === 'daily') dailyChart?.resize()
    else if (viewTab.value === 'monthly') monthlyChart?.resize()
  }

  // Watchers
  watch([reportSummary], () => { if (viewTab.value === 'daily') nextTick(() => requestAnimationFrame(renderDailyChart)) })
  watch([monthlySummary], () => { if (viewTab.value === 'monthly') nextTick(() => requestAnimationFrame(renderMonthlyChart)) })
  watch(viewTab, (tab) => {
    nextTick(() => requestAnimationFrame(() => {
      if (tab === 'daily') { renderDailyChart(); dailyChart?.resize() }
      else if (tab === 'monthly') { renderMonthlyChart(); monthlyChart?.resize() }
    }))
  })

  onMounted(async () => {
    window.addEventListener('resize', handleResize)
    await loadEcharts()
    nextTick(() => requestAnimationFrame(renderDailyChart))
  })

  onUnmounted(() => {
    window.removeEventListener('resize', handleResize)
    disposeCharts()
  })

  return {
    initDailyChart,
    initMonthlyChart,
    renderDailyChart,
    renderMonthlyChart,
    disposeCharts,
  }
}
