<template>
  <section class="page-card flex min-h-0 flex-col overflow-hidden">
    <header class="page-card-header">
      <span class="text-sm font-bold text-heading">
        <FontAwesomeIcon icon="ranking-star" class="mr-1.5 text-primary-500" aria-hidden="true" />
        本月部门排行
      </span>
      <span class="text-xs font-medium text-text-muted">按产量</span>
    </header>

    <div class="page-card-body">
      <UiSkeleton v-if="loading" data-test="rank-skeleton" variant="text" />

      <UiEmpty v-else-if="!ranked.length" data-test="rank-empty" icon="fas fa-ranking-star" text="本月暂无产量" />

      <ol v-else class="flex flex-col gap-3">
        <li v-for="(row, index) in ranked" :key="row.department" data-test="rank-row" class="flex items-center gap-2.5">
          <span class="w-4 shrink-0 text-xs font-bold text-text-muted">{{ index + 1 }}</span>
          <span class="w-14 shrink-0 text-xs font-bold text-heading">{{ row.department_label || label(row.department) }}</span>
          <span
            data-test="rank-bar"
            class="h-2 rounded-full"
            :style="{ width: barWidth(row), background: color(row.department) }"
          />
          <span class="ml-auto text-xs font-bold tabular-nums text-heading">{{ formatNumber(row.total_quantity) }}</span>
        </li>
      </ol>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiSkeleton from '@/components/ui/UiSkeleton.vue'
import { formatNumber } from '@/utils/format'
import type { DepartmentSummary } from '@/types'
import { DEPT_COLORS, DEPT_LABELS } from '../composables/trendChartOption'

const props = defineProps<{
  departments: DepartmentSummary[]
  loading: boolean
}>()

/** 只保留有产量的部门，并按产量降序 —— 全 0 时得到空数组，于是走空态 */
const ranked = computed(() =>
  [...props.departments].filter((d) => d.total_quantity > 0).sort((a, b) => b.total_quantity - a.total_quantity),
)

const maxQuantity = computed(() => ranked.value[0]?.total_quantity ?? 0)

function barWidth(row: DepartmentSummary): string {
  if (!maxQuantity.value) return '0%'
  return `${Math.round((row.total_quantity / maxQuantity.value) * 100)}%`
}

function label(dept: string): string {
  return DEPT_LABELS[dept] ?? dept
}

function color(dept: string): string {
  return DEPT_COLORS[dept] ?? '#94a3b8'
}
</script>
