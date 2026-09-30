<template>
  <div class="flex flex-wrap items-center gap-2 border-b border-border-light bg-surface-card px-4 py-2.5">
    <!-- 区间预设：本周可能跨月，所以「本周」走的是区间而非自然月 -->
    <div class="flex items-center gap-1 rounded-lg bg-surface p-0.5">
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
      :model-value="keywordDraft"
      placeholder="产品名或 69 码…"
      @update:model-value="(v: string) => (keywordDraft = v)"
      @search="onSearch"
      @blur="commitKeyword"
    />

    <!-- 录单人下拉：从当前页记录里去重（后端没有独立的录单人字典接口）。
         若已选中的录单人不在本页记录里（换页后很常见），仍要把当前值并进选项 ——
         否则选中张三后选项塌缩成一个、控件消失，筛选却还在，只能刷新页面才能清掉。 -->
    <UiSelect
      v-if="createdByOptions.length > 1 || filters.createdBy"
      :model-value="filters.createdBy"
      :options="createdBySelectOptions"
      placeholder="全部录单人"
      @update:model-value="(v: string) => emit('update:filters', { ...filters, createdBy: v ?? '', page: 1 })"
    />

    <button
      type="button"
      data-test="drawer-export"
      class="rounded-lg border border-border-light px-3 py-1.5 text-xs font-semibold"
      @click="emit('export')"
    >
      导出
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'

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
  export: []
}>()

const deptOptions = computed(() => [
  { label: '全部部门', value: '' },
  ...props.departments.map((d) => ({ label: DEPT_LABELS[d] ?? d, value: d })),
])

/**
 * 录单人选项：首项固定是「全部录单人」（值为空，与部门下拉同一套做法），
 * 否则选中某个录单人后就没有任何选项能把它清回全部 —— 控件虽在，却退不出去。
 * 当前选中的值也一并并进列表：换页后当前页若没有该录单人，控件仍会显示它。
 */
const createdBySelectOptions = computed(() => {
  const base = props.createdByOptions
  const all = { label: '全部录单人', value: '' }
  if (props.filters.createdBy && !base.some((o) => o.value === props.filters.createdBy)) {
    return [all, { label: props.filters.createdBy, value: props.filters.createdBy }, ...base]
  }
  return [all, ...base]
})

/**
 * 关键词走「草稿 + 提交」而非实时绑定：查询键含完整筛选对象，实时绑定会让每敲一个字
 * 都改键、发一次请求、闪一次骨架屏。草稿从外部筛选同步（如「明细」入口重置筛选）。
 */
const keywordDraft = ref(props.filters.keyword)
watch(
  () => props.filters.keyword,
  (v) => {
    keywordDraft.value = v
  },
)

function commitKeyword() {
  if (keywordDraft.value === props.filters.keyword) return
  emit('update:filters', { ...props.filters, keyword: keywordDraft.value, page: 1 })
}

/** 回车/点搜索图标：先提交关键词（带 page:1），再保留原有的 page 重置信号 */
function onSearch() {
  commitKeyword()
  emit('search')
}

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
