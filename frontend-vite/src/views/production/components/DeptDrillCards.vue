<template>
  <div>
    <UiSkeleton v-if="loading" data-test="dept-skeleton" variant="card" :rows="1" />

    <UiEmpty v-else-if="!departments.length" data-test="dept-empty" icon="fas fa-industry" text="暂无可查看的部门" />

    <div v-else class="grid grid-cols-1 gap-3 md:grid-cols-3">
      <button
        v-for="row in departments"
        :key="row.department"
        type="button"
        data-test="dept-card"
        class="flex items-center gap-3 rounded-[var(--radius-card)] border border-border-light bg-surface-card px-4 py-3 text-left transition-shadow hover:shadow-md"
        :style="{ borderLeft: `4px solid ${color(row.department)}` }"
        @click="emit('drill', row.department)"
      >
        <span class="min-w-0 flex-1">
          <span class="block text-xs font-bold text-heading">{{ label(row.department) }}</span>
          <span class="block text-lg font-extrabold tabular-nums text-heading">
            {{ formatNumber(row.total_quantity) }}
            <small class="text-[11px] font-semibold text-text-muted">件</small>
          </span>
          <span class="block text-[11px] font-medium text-text-muted">
            {{ formatCurrency(row.total_value) }} · {{ row.sku_count }} 种
          </span>
        </span>
        <FontAwesomeIcon icon="chevron-right" class="text-text-muted" aria-hidden="true" />
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiSkeleton from '@/components/ui/UiSkeleton.vue'
import { formatCurrency, formatNumber } from '@/utils/format'
import type { DepartmentSummary } from '@/types'
import { DEPT_COLORS, DEPT_LABELS } from '../composables/trendChartOption'

defineProps<{
  departments: DepartmentSummary[]
  loading: boolean
}>()

const emit = defineEmits<{
  drill: [department: string]
}>()

function label(dept: string): string {
  return DEPT_LABELS[dept] ?? dept
}

function color(dept: string): string {
  return DEPT_COLORS[dept] ?? '#94a3b8'
}
</script>
