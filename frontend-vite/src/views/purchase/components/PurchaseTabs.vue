<template>
  <UiTabs :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)">
    <UiTabTrigger value="orders" class="flex-1">
      <FontAwesomeIcon icon="file-invoice-dollar" aria-hidden="true" /> 采购订单
      <span
        v-if="unprocessedCount > 0"
        :class="['notification-badge', modelValue === 'orders' ? 'notification-badge-active' : '']"
      >{{ unprocessedCount }}</span>
    </UiTabTrigger>
    <UiTabTrigger value="history" class="flex-1"> <FontAwesomeIcon icon="check-circle" aria-hidden="true" /> 下单查询 </UiTabTrigger>
  </UiTabs>
</template>

<script setup lang="ts">
import UiTabs from '@/components/ui/UiTabs.vue'
import UiTabTrigger from '@/components/ui/UiTabTrigger.vue'

defineProps<{
  modelValue: string
  unprocessedCount: number
}>()

defineEmits<{
  'update:modelValue': [value: string]
}>()
</script>
