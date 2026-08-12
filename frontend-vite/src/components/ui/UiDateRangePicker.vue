<script setup lang="ts">
/**
 * UiDateRangePicker — 日期范围选择器
 *
 * 基于 PrimeVue DatePicker range 模式，替换 7 个视图中 9 对手写
 * 双日期选择器（两对独立 UiDatePicker）。
 *
 * Props:
 *   modelValue    - v-model: [startDate: string, endDate: string]
 *   placeholder   - 占位文本
 *   disabled
 *   dateFormat    - 日期格式（默认 'yy-mm-dd'）
 *
 * Emits:
 *   update:modelValue - 双向绑定: [start, end]
 *
 * 示例：
 *   <UiDateRangePicker v-model="dateRange" placeholder="选择日期范围" />
 *   <!-- dateRange.value === ['2025-01-01', '2025-12-31'] -->
 */
import { computed } from 'vue'
import DatePicker from 'primevue/datepicker'

const props = withDefaults(
  defineProps<{
    modelValue?: [string, string] | null
    placeholder?: string
    disabled?: boolean
    dateFormat?: string
  }>(),
  {
    placeholder: '选择日期范围',
    disabled: false,
    dateFormat: 'yy-mm-dd',
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: [string, string] | null]
}>()

const dateRange = computed({
  get: () => {
    if (!props.modelValue || !props.modelValue[0] || !props.modelValue[1]) return null
    return [new Date(props.modelValue[0]), new Date(props.modelValue[1])]
  },
  set: (val) => {
    if (!val || !Array.isArray(val) || val.length < 2 || val[0] == null || val[1] == null) {
      emit('update:modelValue', null)
      return
    }
    const start = _formatDate(val[0])
    const end = _formatDate(val[1])
    emit('update:modelValue', [start, end])
  },
})

function _formatDate(d: string | Date): string {
  if (typeof d === 'string') return d
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}
</script>

<template>
  <DatePicker
    v-model="dateRange"
    selectionMode="range"
    :placeholder="placeholder"
    :disabled="disabled"
    :dateFormat="dateFormat"
    showIcon
    iconDisplay="input"
  />
</template>
