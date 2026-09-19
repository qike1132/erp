<template>
  <button :class="buttonClasses" :disabled="disabled" :type="htmlType">
    <slot />
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    variant?: 'primary' | 'success' | 'warning' | 'danger' | 'outline' | 'ghost'
    size?: 'sm' | 'md' | 'lg'
    disabled?: boolean
    htmlType?: 'button' | 'submit' | 'reset'
  }>(),
  {
    variant: 'primary',
    size: 'md',
    disabled: false,
    htmlType: 'button',
  },
)

const baseClasses =
  'inline-flex items-center gap-1.5 font-medium cursor-pointer whitespace-nowrap tabular-nums transition-colors transition-transform transition-shadow duration-300 border focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 focus-visible:ring-offset-2 active:translate-y-0'

const variantClasses: Record<string, string> = {
  primary:
    'bg-gradient-primary text-white border-transparent shadow-sm hover:shadow-md hover:-translate-y-0.5',
  success:
    'bg-gradient-success text-white border-transparent shadow-sm hover:shadow-md hover:-translate-y-0.5',
  warning:
    'bg-gradient-warning text-white border-transparent shadow-sm hover:shadow-md hover:-translate-y-0.5',
  danger:
    'bg-gradient-danger text-white border-transparent shadow-sm hover:shadow-md hover:-translate-y-0.5',
  outline:
    'bg-transparent text-text-secondary border-border hover:text-ocean-text hover:border-ocean hover:bg-ocean-light/30',
  ghost: 'bg-transparent text-text-secondary border-transparent hover:bg-ocean-light/30',
}

const sizeClasses: Record<string, string> = {
  sm: 'px-3 py-1.5 text-xs rounded-[var(--radius-input)]',
  md: 'px-5 py-2.5 text-sm rounded-[var(--radius-button)]',
  lg: 'px-7 py-3 text-sm rounded-[var(--radius-button)]',
}

const buttonClasses = computed(() =>
  [
    baseClasses,
    variantClasses[props.variant],
    sizeClasses[props.size],
    props.disabled ? 'opacity-50 !cursor-not-allowed !translate-y-0 !shadow-none' : '',
  ].join(' '),
)
</script>
