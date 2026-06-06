<template>
  <div
    class="w-full h-2 bg-border-light rounded-full overflow-hidden"
    role="progressbar"
    :aria-valuenow="Math.round(Math.min(Math.max(percent, 0), 100))"
    aria-valuemin="0"
    aria-valuemax="100"
  >
    <div
      class="h-full rounded-full transition-[width] duration-300"
      :class="colorClass"
      :style="{ width: `${Math.min(Math.max(percent, 0), 100)}%` }"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    percent: number
    variant?: 'primary' | 'success' | 'warning' | 'danger'
  }>(),
  { variant: 'primary' },
)

const colorClass = computed(
  () =>
    ({
      primary: 'bg-primary-500',
      success: 'bg-success-500',
      warning: 'bg-warning-500',
      danger: 'bg-danger-500',
    })[props.variant],
)
</script>
