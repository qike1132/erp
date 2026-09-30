<template>
  <div class="flex flex-wrap items-center gap-2 border-b border-border-light bg-surface-card px-4 py-2.5">
    <!-- 区间预设：本周可能跨月，所以「本周」走的是区间而非自然月 -->
    <div class="flex items-center gap-1 rounded-lg bg-surface-sunken p-0.5">
      <button
        v-for="p in PRESETS"
        :key="p.value"
        type="button"
        class="rounded-md px-2.5 py-1 text-xs font-semibold transition-colors"
        :class="filters.preset === p.value ? 'bg-primary-600 text-white' : 'text-text-secondary hover:text-heading'"
        @click="emit('update:filters', { ...filters, preset: p.value, page: 1 })"
      >
        {{ p.label }}
      </button>
    </div>

    <UiDateRangePicker
      v-if="filters.preset === 'custom'"
      :model-value="customRange"
      placeholder="选择区间"
      @update:model-value="onCustomRange"
    />

    <!-- 部门下拉只列后端返回的可见部门（受限用户看到的更少），不硬编码三个 -->
    <UiSelect
      :model-value="filters.department"
      :options="deptOptions"
      placeholder="全部部门"
      @update:model-value="(v: string) => emit('update:filters', { ...filters, department: v ?? '', page: 1 })"
    />

    <UiSearchInput
      :model-value="filters.keyword"
      placeholder="产品名或 69 码…"
      @update:model-value="(v: string) => emit('update:filters', { ...filters, keyword: v })"
      @search="emit('search')"
    />

    <!-- 只有一个录单人时该筛选器没有意义，直接不显示 -->
    <UiSelect
      v-if="createdByOptions.length > 1"
      :model-value="filters.createdBy"
      :options="createdByOptions"
      placeholder="全部录单人"
      @update:model-value="(v: string) => emit('update:filters', { ...filters, createdBy: v ?? '', page: 1 })"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import UiDateRangePicker from '@/components/ui/UiDateRangePicker.vue'
import UiSearchInput from '@/components/ui/UiSearchInput.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import { DEPT_LABELS } from '../composables/trendChartOption'
import type { RecordFilters } from '../composables/recordFilters'

const PRESETS = [
  { label: '今日', value: 'today' },
  { label: '本周', value: 'week' },
  { label: '本月', value: 'month' },
  { label: '自定义', value: 'custom' },
] as const

const props = defineProps<{
  filters: RecordFilters
  /** 后端返回的可见部门键；只列这些，不硬编码三个 */
  departments: string[]
  /** 可选的录单人；少于 2 个时该筛选器不显示（避免只有一个选项的下拉） */
  createdByOptions: Array<{ label: string; value: string }>
}>()

const emit = defineEmits<{
  'update:filters': [value: RecordFilters]
  search: []
}>()

const deptOptions = computed(() => [
  { label: '全部部门', value: '' },
  ...props.departments.map((d) => ({ label: DEPT_LABELS[d] ?? d, value: d })),
])

const customRange = computed<[string, string] | null>(() =>
  props.filters.customStart && props.filters.customEnd
    ? [props.filters.customStart, props.filters.customEnd]
    : null,
)

function onCustomRange(value: [string, string] | null) {
  emit('update:filters', {
    ...props.filters,
    customStart: value?.[0] ?? '',
    customEnd: value?.[1] ?? '',
    page: 1,
  })
}
</script>
