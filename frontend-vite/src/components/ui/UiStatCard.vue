<template>
  <div
    :class="[
      'bg-surface-card rounded-[var(--radius-card)] border border-border-light p-5 shadow-sm transition-all duration-300',
      accentClass,
    ]"
    style="border-left-width: 4px"
  >
    <div class="flex items-start justify-between">
      <div class="flex-1">
        <div class="text-[11px] text-text-secondary uppercase tracking-[1.2px] mb-2 font-medium">
          <slot name="label" />
        </div>
        <div class="text-3xl font-extrabold text-heading">
          <slot />
        </div>
        <div v-if="$slots.extra" class="text-xs text-text-muted mt-2">
          <slot name="extra" />
        </div>
      </div>
      <div v-if="$slots.icon" class="ml-4">
        <slot name="icon" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    accent?: 'blue' | 'green' | 'amber' | 'red' | 'purple' | 'ocean'
  }>(),
  { accent: 'blue' },
)

const accentClass: Record<string, string> = {
  blue: 'border-l-primary-500 hover:-translate-y-1 hover:shadow-md hover:border-l-primary-400',
  green: 'border-l-success-500 hover:-translate-y-1 hover:shadow-md hover:border-l-success-400',
  amber: 'border-l-warning-500 hover:-translate-y-1 hover:shadow-md hover:border-l-warning-400',
  red: 'border-l-danger-500 hover:-translate-y-1 hover:shadow-md hover:border-l-danger-400',
  purple: 'border-l-purple-500 hover:-translate-y-1 hover:shadow-md hover:border-l-purple-400',
  ocean: 'border-l-ocean-deep hover:-translate-y-1 hover:shadow-md hover:border-l-ocean',
}
</script>
