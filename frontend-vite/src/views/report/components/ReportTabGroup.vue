<template>
  <div class="rp-tab-group">
    <UiTabs :model-value="modelValue" @update:model-value="onChange">
      <UiTabTrigger
        v-for="tab in REPORT_TABS"
        :key="tab.value"
        :value="tab.value"
        :active="modelValue === tab.value"
      >
        {{ tab.label }}
      </UiTabTrigger>
    </UiTabs>
  </div>
</template>

<script setup lang="ts">
/**
 * ReportTabGroup.vue — 报表维度 tab
 *
 * 直接用系统的 UiTabs + UiTabTrigger（其他页面的 tab 导航同款），
 * 而不是自己写一套样式 —— 自绘版本与系统 tab 的观感不一致（2026-09-29 反馈）。
 * 本组件只负责把 useReportConfig 的 tab 清单映射成触发器。
 */
import UiTabs from '@/components/ui/UiTabs.vue'
import UiTabTrigger from '@/components/ui/UiTabTrigger.vue'
import { REPORT_TABS, type TabType } from '../composables/useReportConfig'

defineProps<{ modelValue: TabType }>()

const emit = defineEmits<{ 'change': [value: TabType] }>()

function onChange(value: string) {
  emit('change', value as TabType)
}
</script>

<style scoped>
/* UiTabs 自带 margin-bottom: 20px（为「tab 独占一行」的导航设计）。
   本页 tab 与标题、筛选同处单行工具条内，需去掉这个外边距，
   否则整组 tab 在 flex 行里会上浮错位。 */
.rp-tab-group :deep(.ui-tab-group) {
  margin-bottom: 0;
}
</style>
