<template>
  <div class="animate-pulse" :class="variantClass">
    <template v-if="variant === 'card'">
      <div class="h-4 bg-slate-200 rounded w-3/4 mb-3" />
      <div class="h-4 bg-slate-200 rounded w-1/2 mb-3" />
      <div class="h-10 bg-slate-200 rounded" />
    </template>
    <template v-else-if="variant === 'table'">
      <div class="flex gap-4 mb-4">
        <div v-for="i in rows" :key="'th-' + i" class="h-4 bg-slate-200 rounded flex-1" />
      </div>
      <div v-for="i in rows" :key="'tr-' + i" class="flex gap-4 mb-3">
        <div v-for="j in 4" :key="'td-' + i + '-' + j" class="h-4 bg-slate-100 rounded flex-1" />
      </div>
    </template>
    <template v-else-if="variant === 'stat'">
      <div class="flex items-center justify-between">
        <div class="flex-1">
          <div class="h-3 bg-slate-200 rounded w-16 mb-2" />
          <div class="h-8 bg-slate-200 rounded w-20 mb-2" />
          <div class="h-3 bg-slate-100 rounded w-12" />
        </div>
        <div class="w-10 h-10 bg-slate-200 rounded-xl" />
      </div>
    </template>
    <template v-else>
      <div class="h-4 bg-slate-200 rounded w-full mb-3" />
      <div class="h-4 bg-slate-200 rounded w-2/3" />
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    variant?: 'text' | 'card' | 'table' | 'stat'
    rows?: number
  }>(),
  {
    variant: 'text',
    rows: 5,
  },
)

const variantClass = computed(() => {
  if (props.variant === 'stat') return 'p-5 rounded-[var(--radius-card)] border border-border-light bg-surface-card'
  if (props.variant === 'card') return 'p-6 rounded-[var(--radius-card)] border border-border-light bg-surface-card'
  return ''
})
</script>
