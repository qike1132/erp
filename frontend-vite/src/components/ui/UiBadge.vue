<template>
  <span :class="badgeClasses">
    <slot />
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    variant?: 'pending' | 'completed' | 'cancelled' | 'unprocessed' | 'processing' | 'info'
  }>(),
  {
    variant: 'pending',
  },
)

const variantClasses: Record<string, string> = {
  pending: 'bg-warning-50 text-warning-700 border-warning-200',
  completed: 'bg-success-50 text-success-700 border-success-200',
  cancelled: 'bg-danger-50 text-danger-700 border-danger-200',
  unprocessed: 'bg-info-50 text-info-700 border-info-200',
  processing: 'bg-primary-50 text-primary-700 border-primary-200',
  info: 'bg-ocean-light/40 text-ocean-text border-ocean',
}

const badgeClasses = computed(
  () =>
    `inline-flex items-center gap-1 px-2.5 py-0.5 rounded-[var(--radius-sm)] text-xs font-medium border ${variantClasses[props.variant]}`,
)
</script>
