<template>
  <span class="inline-flex items-center px-2.5 py-0.5 rounded-[var(--radius-sm)] text-xs font-medium border" :class="variantClass">
    <slot />
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    variant?: 'default' | 'primary' | 'success' | 'warning' | 'danger' | 'info'
  }>(),
  { variant: 'default' },
)

const variantClass = computed(
  () =>
    ({
      default: 'bg-border-light text-text-secondary border-border',
      primary: 'bg-primary-50 text-primary-700 border-primary-200',
      success: 'bg-success-50 text-success-700 border-success-200',
      warning: 'bg-warning-50 text-warning-700 border-warning-200',
      danger: 'bg-danger-50 text-danger-700 border-danger-200',
      info: 'bg-ocean-light/40 text-ocean-text border-ocean',
    })[props.variant],
)
</script>
