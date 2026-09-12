<template>
  <div
    :class="[
      'kpi-card group bg-surface-card rounded-[var(--radius-card)] border border-border-light p-4 md:p-5 shadow-sm cursor-default select-none',
      accentBorderClass,
    ]"
    :style="animationStyle"
  >
    <div class="flex items-start justify-between">
      <div class="flex-1 min-w-0">
        <div class="flex items-center gap-1.5 mb-2">
          <span class="text-[10px] md:text-[12px] text-text-secondary uppercase tracking-[1px] font-semibold">
            {{ label }}
          </span>
        </div>
        <div class="text-2xl md:text-[28px] font-semibold text-heading tabular-nums leading-tight">
          <template v-if="isLoading">
            <div class="h-8 md:h-9 w-16 bg-slate-100 rounded-[var(--radius-md)] animate-pulse" />
          </template>
          <template v-else>
            <CountUp :target="value" :duration="1200" />
          </template>
        </div>
        <div v-if="trendText && !isLoading" class="flex items-center gap-1 mt-1.5">
          <span
            :class="[
              'text-[10px] md:text-xs font-semibold px-1.5 py-0.5 rounded-[6px]',
              trend > 0 ? 'text-success-600 bg-success-50' :
              trend < 0 ? 'text-danger-600 bg-danger-50' :
              'text-text-muted bg-slate-100',
            ]"
          >
            {{ trendText }}
          </span>

          <span class="text-[10px] text-text-muted">较昨日</span>
        </div>
        <div v-else-if="isLoading" class="mt-1.5">
          <div class="h-4 w-20 bg-slate-100 rounded-[var(--radius-sm)] animate-pulse" />
        </div>
      </div>
      <div
        :class="[
          'w-9 h-9 md:w-10 md:h-10 rounded-[var(--radius-md)] flex items-center justify-center shrink-0',
          iconBgClass,
        ]"
      >
        <FontAwesomeIcon :icon="icon" :class="['text-sm md:text-base', iconColorClass]" aria-hidden="true" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import CountUp from './CountUp.vue'

const props = defineProps<{
  label: string
  value: number
  trend: number
  trendText: string
  icon: string
  accent: 'blue' | 'green' | 'amber' | 'red' | 'purple' | 'ocean'
  delay?: number
  isLoading?: boolean
}>()

const accentBorderClass: Record<string, string> = {
  blue: 'border-l-[3px] border-l-primary-500',
  green: 'border-l-[3px] border-l-success-500',
  amber: 'border-l-[3px] border-l-warning-500',
  red: 'border-l-[3px] border-l-danger-500',
  purple: 'border-l-[3px] border-l-purple-500',
  ocean: 'border-l-[3px] border-l-ocean-deep',
}

const iconBgClass: Record<string, string> = {
  blue: 'bg-primary-50',
  green: 'bg-success-50',
  amber: 'bg-warning-50',
  red: 'bg-danger-50',
  purple: 'bg-purple-50',
  ocean: 'bg-ocean-light',
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
.kpi-card {
  animation: slideUp 0.5s cubic-bezier(0.175, 0.885, 0.32, 1.275) both;
}

@keyframes slideUp {
  from {
    opacity: 0;
    transform: translateY(16px) scale(0.96);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}
</style>
