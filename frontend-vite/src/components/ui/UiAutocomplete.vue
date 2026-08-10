<script setup lang="ts" generic="T extends Record<string, unknown>">
/**
 * UiAutocomplete — 产品/资源搜索自动补全
 *
 * 基于 PrimeVue AutoComplete，封装为标准接口。
 * 消除 5 个视图 664 行重复的 autocomplete 代码。
 *
 * Props:
 *   modelValue     - v-model: 搜索文本
 *   suggestions    - 外部传入的建议列表（静态模式）
 *   searchFn       - 远程搜索函数: (query: string) => Promise<T[]>
 *   optionLabel    - 显示字段名（默认 'name'）
 *   placeholder
 *   disabled
 *   debounceMs     - 防抖毫秒（默认 300）
 *   minQueryLength - 最小触发搜索长度（默认 1）
 *
 * Emits:
 *   update:modelValue - v-model 双向绑定
 *   select            - 选中项: (item: T) => void
 *   search            - 搜索文本变化: (query: string) => void
 *
 * Slots:
 *   option   - 自定义选项模板: { item, index }
 *   header   - 列表头部
 *   footer   - 列表尾部
 *
 * 示例：
 *   <UiAutocomplete
 *     v-model="searchText"
 *     :searchFn="api.searchProducts"
 *     placeholder="输入产品名称搜索"
 *     optionLabel="name"
 *     @select="onSelect"
 *   >
 *     <template #option="{ item }">
 *       {{ item.name }} <span class="text-xs text-text-muted">{{ item.barcode }}</span>
 *     </template>
 *   </UiAutocomplete>
 */
import { ref, watch } from 'vue'
import AutoComplete from 'primevue/autocomplete'
import type { AutoCompleteCompleteEvent } from 'primevue'

const props = withDefaults(
  defineProps<{
    modelValue?: string
    suggestions?: T[]
    searchFn?: (query: string) => Promise<T[]>
    optionLabel?: string
    placeholder?: string
    disabled?: boolean
    debounceMs?: number
    minQueryLength?: number
    /** PrimeVue AutoComplete appendTo。默认 'body' 保证父容器 overflow:hidden 时不裁剪。
     * 传 undefined 则渲染在组件树内（适用于无裁剪风险的场景，避免 body 级重排跳动）。 */
    appendTo?: string
  }>(),
  {
    modelValue: '',
    suggestions: () => [],
    placeholder: '请输入搜索关键词',
    disabled: false,
    minQueryLength: 1,
    optionLabel: 'name',
    appendTo: 'body',
  },
)

defineSlots<{
  option: (props: { item: T; index: number }) => unknown
  header: () => unknown
  footer: () => unknown
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  select: [item: T]
  search: [query: string]
}>()

// ============================================================
// 内部状态
// ============================================================
const internalSuggestions = ref<T[]>([])
const loading = ref(false)
let requestSeq = 0

// ============================================================
// 搜索逻辑 — @complete 驱动搜索 + requestSeq 防过期
// ============================================================
function onInputChange(value: string) {
  emit('update:modelValue', value)
}

function onComplete(event: AutoCompleteCompleteEvent) {
  triggerSearch(event.query)
}

function triggerSearch(query: string) {
  const q = query.trim()

  // 静态建议列表
  if (props.suggestions && props.suggestions.length > 0) {
    const ql = q.toLowerCase()
    internalSuggestions.value = props.suggestions.filter((item) => {
      const label = item[props.optionLabel!]
      return typeof label === 'string' && label.toLowerCase().includes(ql)
    })
    emit('search', q)
    return
  }

  // 远程搜索
  if (!props.searchFn || q.length < props.minQueryLength!) {
    internalSuggestions.value = []
    return
  }

  const seq = ++requestSeq
  loading.value = true

  props.searchFn(q)
    .then((results) => {
      if (seq === requestSeq) {
        internalSuggestions.value = results || []
        loading.value = false
      }
    })
    .catch(() => {
      if (seq === requestSeq) {
        internalSuggestions.value = []
        loading.value = false
      }
    })

  emit('search', q)
}

function onItemSelect(event: { value: T }) {
  emit('select', event.value)
}

// 当外部 suggestions 变化时同步
watch(
  () => props.suggestions,
  (val) => {
    if (val?.length) {
      internalSuggestions.value = [...val]
    }
  },
  { immediate: true },
)
</script>

<template>
  <AutoComplete
    :modelValue="modelValue"
    :suggestions="internalSuggestions"
    :optionLabel="(optionLabel as string)"
    :placeholder="placeholder"
    :disabled="disabled"
    :loading="loading"
    :minLength="minQueryLength"
    :appendTo="(appendTo as string | undefined)"
    @update:modelValue="onInputChange"
    @complete="onComplete"
    @item-select="onItemSelect"
  >
    <template v-if="$slots.option" #option="slotProps">
      <slot name="option" :item="slotProps.option" :index="slotProps.index" />
    </template>
  </AutoComplete>
</template>
