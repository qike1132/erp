<template>
  <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
    <template v-if="today && monthly">
      <UiStatCard accent="blue">
        <template #label>今日产量</template>
        <template #default>
          {{ formatNumber(today.overall_quantity) }}<small class="ml-1 text-xs font-semibold text-text-muted">件</small>
        </template>
        <template #extra>
          <span :class="deltaClass(quantityDelta.tone)">较昨日 {{ quantityDelta.text }}</span>
        </template>
      </UiStatCard>

      <UiStatCard accent="green">
        <template #label>今日产值</template>
        <template #default>{{ formatCurrency(today.overall_value) }}</template>
        <template #extra>
          <span :class="deltaClass(valueDelta.tone)">较昨日 {{ valueDelta.text }}</span>
        </template>
      </UiStatCard>

      <UiStatCard accent="amber">
        <template #label>本月累计</template>
        <template #default>
          {{ formatNumber(monthly.monthly_total_quantity) }}<small class="ml-1 text-xs font-semibold text-text-muted">件</small>
        </template>
        <template #extra>{{ productionDays }} 个生产日</template>
      </UiStatCard>

      <UiStatCard accent="ocean">
        <template #label>日均产量</template>
        <template #default>
          {{ formatNumber(Math.round(average)) }}<small class="ml-1 text-xs font-semibold text-text-muted">件</small>
        </template>
        <template #extra>
          <span :class="deltaClass(averageDelta.tone)">较上月 {{ averageDelta.text }}</span>
        </template>
      </UiStatCard>
    </template>

    <UiSkeleton v-else data-test="kpi-skeleton" variant="stat" class="col-span-2 lg:col-span-4" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import UiSkeleton from '@/components/ui/UiSkeleton.vue'
import UiStatCard from '@/components/ui/UiStatCard.vue'
import { formatCurrency, formatNumber } from '@/utils/format'
import type { DailySummary, MonthlySummary } from '@/types'
import { countProductionDays, dailyAverage, formatDelta } from '../composables/kpiDelta'

const props = defineProps<{
  today: DailySummary | null
  yesterday: DailySummary | null
  monthly: MonthlySummary | null
  /** 上月汇总，只用于算"日均较上月"；为 null 时该处显示破折号 */
  previousMonth: MonthlySummary | null
}>()

const quantityDelta = computed(() =>
  formatDelta(props.today?.overall_quantity ?? 0, props.yesterday?.overall_quantity ?? 0),
)
const valueDelta = computed(() =>
  formatDelta(props.today?.overall_value ?? 0, props.yesterday?.overall_value ?? 0),
)

const productionDays = computed(() => countProductionDays(props.monthly?.daily_data))
const average = computed(() =>
  dailyAverage(props.monthly?.monthly_total_quantity ?? 0, productionDays.value),
)

/** 日均较上月：两边都按"当月累计 ÷ 生产天数"算，量纲一致 */
const averageDelta = computed(() => {
  const prevDays = countProductionDays(props.previousMonth?.daily_data)
  if (!prevDays) return formatDelta(0, 0)
  const prevAverage = dailyAverage(props.previousMonth?.monthly_total_quantity ?? 0, prevDays)
  return formatDelta(average.value, prevAverage)
})

function deltaClass(tone: 'up' | 'down' | 'flat'): string {
  if (tone === 'up') return 'text-success-600'
  if (tone === 'down') return 'text-danger-600'
  return 'text-text-muted'
}
</script>
