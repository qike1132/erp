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
      @clear="onClear"
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
import type { RangePreset, RecordFilters } from '../composables/recordFilters'

/** 各预设的中文名。键必须穷举 RangePreset —— 新增预设而忘了配中文名时，
 *  下面的 satisfies 会让 type-check 直接红，而不是渲染出空按钮。 */
const PRESET_LABELS = {
  today: '今日',
  week: '本周',
  month: '本月',
  custom: '自定义',
} as const satisfies Record<RangePreset, string>

/** 渲染顺序也在这里定死：从左到右时间粒度递增，自定义永远在最后 */
const PRESETS: ReadonlyArray<{ label: string; value: RangePreset }> = (
  Object.keys(PRESET_LABELS) as RangePreset[]
).map((value) => ({ label: PRESET_LABELS[value], value }))

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

/**
 * 点 × 清空：输入框不聚焦时（先点过别处、再回头点 ×）不会触发 blur，
 * 若不在此处提交，框已空而筛选还挂着旧关键词 —— 列表看着"清不掉"。
 * 草稿与筛选一并清零，载荷与 commitKeyword 同构（page:1）。
 */
function onClear() {
  keywordDraft.value = ''
  if (props.filters.keyword === '') return
  emit('update:filters', { ...props.filters, keyword: '', page: 1 })
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
