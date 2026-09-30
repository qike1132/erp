<template>
  <section class="page-card flex min-h-0 flex-col overflow-hidden">
    <header class="page-card-header">
      <span class="text-sm font-bold text-heading">
        <FontAwesomeIcon icon="chart-column" class="mr-1.5 text-primary-500" aria-hidden="true" />
        近 {{ DAYS }} 日产量
      </span>
      <span v-if="trend" class="text-xs font-medium text-text-muted">
        {{ trend.start_date }} ~ {{ trend.end_date }} · 按部门堆叠
      </span>
    </header>

    <div class="page-card-body">
      <UiSkeleton v-if="loading" data-test="trend-skeleton" variant="card" />

      <UiEmpty
        v-else-if="!hasData"
        data-test="trend-empty"
        icon="fas fa-chart-column"
        text="该区间内暂无生产数据"
      />

      <div v-else ref="chartEl" data-test="trend-chart" class="h-[260px] w-full" />
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch, nextTick } from 'vue'
import type { EChartsType } from 'echarts/core'

import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiSkeleton from '@/components/ui/UiSkeleton.vue'
import { ensureEcharts } from '@/utils/echartsPreload'
import type { TrendResponse } from '@/types'
import { buildTrendOption } from '../composables/trendChartOption'

const DAYS = 30

const props = defineProps<{
  trend: TrendResponse | null
  loading: boolean
}>()

const chartEl = ref<HTMLElement | null>(null)
let chart: EChartsType | null = null

const hasData = computed(() => !!props.trend?.days.some((d) => d.total > 0))

async function render() {
  if (!hasData.value || !chartEl.value) return
  const echarts = await ensureEcharts()
  if (!chartEl.value) return
  if (!chart || chart.isDisposed()) chart = echarts.init(chartEl.value)
  chart.setOption(buildTrendOption(props.trend!.days, props.trend!.departments), true)
  chart.resize()
}

function dispose() {
  chart?.dispose()
  chart = null
}

function onResize() {
  chart?.resize()
}

onMounted(() => {
  window.addEventListener('resize', onResize)
  nextTick(render)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  dispose()
})

watch(
  () => [props.trend, hasData.value],
  () => {
    if (!hasData.value) {
      dispose()
      return
    }
    nextTick(render)
  },
)
</script>
