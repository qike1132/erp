<template>
  <div
    :class="[
      'bg-surface-card rounded-[var(--radius-card)] border border-border-light card-hover overflow-hidden',
      shadowClass,
      paddingClass,
    ]"
  >
    <div
      v-if="$slots.header"
      :class="[
        'px-6 py-4 border-b border-border-light flex justify-between items-center rounded-t-[var(--radius-card)]',
        headerGradient ? 'bg-gradient-card-header' : '',
      ]"
    >
      <slot name="header" />
    </div>
    <div v-if="$slots.default" :class="bodyPadding ? 'p-6' : ''">
      <slot />
    </div>
    <div v-if="$slots.footer" class="px-6 py-4 border-t border-border-light flex justify-end gap-3">
      <slot name="footer" />
    </div>
  </div>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    paddingClass?: string
    bodyPadding?: boolean
    headerGradient?: boolean
    shadowClass?: string
  }>(),
  {
    paddingClass: 'mb-4',
    bodyPadding: true,
    headerGradient: false,
    shadowClass: 'shadow-sm',
  },
)
</script>
