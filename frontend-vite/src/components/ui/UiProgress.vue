<template>
  <div class="w-full">
    <div v-if="label" class="text-xs font-semibold text-text-secondary mb-1 uppercase tracking-wider">
      {{ label }}
    </div>
    <div class="w-full bg-gray-200 rounded-full h-2 overflow-hidden">
      <div
        class="h-full rounded-full transition-all duration-300"
        :class="colorClass"
        :style="{ width: `${Math.min(100, Math.max(0, percentage))}%` }"
      />
    </div>
    <div v-if="showText" class="text-xs text-text-secondary mt-1 text-right">{{ percentage }}%</div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  percentage: number
  status?: 'success' | 'warning' | 'danger' | 'primary'
  label?: string
  showText?: boolean
}>()

const colorClass = computed(() => {
  switch (props.status) {
    case 'success':
      return 'bg-success-500'
    case 'warning':
      return 'bg-warning-500'
    case 'danger':
      return 'bg-danger-500'
    default:
      return 'bg-primary-500'
  }
})
</script>
