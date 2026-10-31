<template>
  <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
    <template v-if="today && monthly">
      <UiStatCard accent="blue">
        <template #label>今日产量</template>
        <template #default>
          {{ formatNumber(today.overall_quantity) }}<UnitPiece />
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
          {{ formatNumber(monthly.monthly_total_quantity) }}<UnitPiece />
        </template>
        <template #extra>{{ productionDays }} 个生产日</template>
      </UiStatCard>

      <UiStatCard accent="ocean">
        <template #label>日均产量</template>
        <template #default>
          {{ formatNumber(Math.round(average)) }}<UnitPiece />
        </template>
        <template #extra>
          <span :class="deltaClass(averageDelta.tone)">较上月 {{ averageDelta.text }}</span>
        </template>
      </UiStatCard>
    </template>

    <!-- 加载失败（A-M33）：原先没有数据就恒显骨架屏，请求失败时会永远转圈；
         失败必须显示成失败，并给一个重试入口 -->
    <div
      v-else-if="loadFailed"
      class="col-span-2 flex flex-col items-center gap-2 rounded-xl border border-danger-200 bg-danger-50 px-4 py-6 text-sm text-danger-700 lg:col-span-4"
      role="alert"
      data-test="kpi-error"
    >
      <span>汇总数据加载失败，暂时无法显示 KPI</span>
      <UiButton size="sm" variant="outline" @click="emit('retry')">重试</UiButton>
    </div>

    <UiSkeleton v-else data-test="kpi-skeleton" variant="stat" class="col-span-2 lg:col-span-4" />
  </div>
</template>

<script setup lang="ts">
import { computed, h } from 'vue'

import UiSkeleton from '@/components/ui/UiSkeleton.vue'
import UiButton from '@/components/ui/UiButton.vue'
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
  /**
   * 汇总请求是否失败（A-M33）。没有数据时用它区分「还在加载」与「加载失败」：
   * 前者该转圈，后者该报错 + 重试；否则失败会表现为永远转圈的骨架屏。
   */
  loadFailed?: boolean
}>()

const emit = defineEmits<{ retry: [] }>()

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

/** 三张产量卡的单位后缀「件」—— 同一处定义，避免三份相同的 class 串散落模板 */
function UnitPiece() {
  return h('small', { class: 'ml-1 text-xs font-semibold text-text-muted' }, '件')
}
</script>
