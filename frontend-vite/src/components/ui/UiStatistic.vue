<template>
  <div class="bg-white rounded-2xl shadow-sm border border-border-light p-6 card-hover">
    <div class="text-text-secondary text-xs font-semibold uppercase tracking-wider mb-1">
      {{ title }}
    </div>
    <div class="text-2xl font-bold text-text min-w-0 tabular-nums">
      {{ formattedValue }}
    </div>
    <div v-if="suffix" class="text-sm text-text-muted ml-1 inline">
      {{ suffix }}
    </div>
    <div v-if="prefix" class="text-sm text-text-muted mr-1 inline">
      {{ prefix }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { formatNumber } from '@/utils/format'

const props = defineProps<{
  title: string
  value: number | string
  suffix?: string
  prefix?: string
  formatter?: (val: number | string) => string
}>()

const formattedValue = computed(() => {
  if (props.formatter) return props.formatter(props.value)
  if (typeof props.value === 'number') return formatNumber(props.value)
  return props.value
})
</script>
