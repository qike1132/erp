<template>
  <RouterLink
    :to="to"
    :class="[
      'quick-action group flex items-center gap-3 md:gap-4 bg-surface-card rounded-[18px] border border-border-light p-3.5 md:p-5 shadow-sm cursor-pointer no-underline',
      accentHoverClass,
    ]"
    :style="animationStyle"
  >
    <div
      :class="[
        'w-10 h-10 md:w-12 md:h-12 rounded-xl flex items-center justify-center shrink-0 transition-all duration-300 group-hover:scale-110',
        iconBgClass,
      ]"
    >
      <i :class="['fas', icon, 'text-sm md:text-lg', iconColorClass]" aria-hidden="true" />
    </div>
    <div class="flex-1 min-w-0">
      <div class="text-sm md:text-[15px] font-bold text-heading truncate">
        {{ label }}
      </div>
      <div class="text-[11px] md:text-xs text-text-secondary truncate mt-0.5">
        {{ description }}
      </div>
    </div>
    <div class="shrink-0 opacity-0 -translate-x-2 transition-all duration-300 group-hover:opacity-100 group-hover:translate-x-0">
      <i class="fas fa-chevron-right text-xs text-text-muted" />
    </div>
  </RouterLink>
</template>

<script setup lang="ts">
import { RouterLink } from 'vue-router'

const props = defineProps<{
  label: string
  description: string
  icon: string
  to: string
  accent: 'blue' | 'green' | 'amber' | 'red' | 'purple' | 'ocean'
  delay?: number
}>()

const accentHoverClass: Record<string, string> = {
  blue: 'hover:border-primary-300 hover:shadow-md hover:-translate-y-0.5',
  green: 'hover:border-success-300 hover:shadow-md hover:-translate-y-0.5',
  amber: 'hover:border-warning-300 hover:shadow-md hover:-translate-y-0.5',
  red: 'hover:border-danger-300 hover:shadow-md hover:-translate-y-0.5',
  purple: 'hover:border-purple-300 hover:shadow-md hover:-translate-y-0.5',
  ocean: 'hover:border-ocean-deep hover:shadow-md hover:-translate-y-0.5',
}

const iconBgClass: Record<string, string> = {
  blue: 'bg-primary-50 group-hover:bg-primary-100',
  green: 'bg-success-50 group-hover:bg-success-100',
  amber: 'bg-warning-50 group-hover:bg-warning-100',
  red: 'bg-danger-50 group-hover:bg-danger-100',
  purple: 'bg-purple-50 group-hover:bg-purple-100',
  ocean: 'bg-ocean-light group-hover:bg-ocean',
}

const iconColorClass: Record<string, string> = {
  blue: 'text-primary-600',
  green: 'text-success-600',
  amber: 'text-warning-600',
  red: 'text-danger-600',
  purple: 'text-purple-600',
  ocean: 'text-ocean-text',
}

const animationStyle = {
  animationDelay: `${props.delay ?? 0}ms`,
}
</script>

<style scoped>
.quick-action {
  animation: slideUp 0.45s cubic-bezier(0.175, 0.885, 0.32, 1.275) both;
  transition: box-shadow 0.25s ease, transform 0.25s ease, border-color 0.25s ease;
}

@keyframes slideUp {
  from {
    opacity: 0;
    transform: translateY(12px) scale(0.97);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}
</style>
