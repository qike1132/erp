<template>
  <header class="flex shrink-0 items-center gap-3 border-b border-border-light bg-surface-card px-6 py-3">
    <div class="flex items-center gap-1.5">
      <button class="flex h-8 w-8 items-center justify-center rounded-lg border border-border-light" aria-label="前一天" @click="emit('prev-day')">
        <FontAwesomeIcon icon="chevron-left" aria-hidden="true" />
      </button>
      <input
        :value="date"
        type="date"
        class="rounded-lg border border-border-light px-2.5 py-1.5 text-sm font-semibold tabular-nums"
        aria-label="日期选择"
        @input="emit('update:date', ($event.target as HTMLInputElement).value)"
      />
      <button class="flex h-8 w-8 items-center justify-center rounded-lg border border-border-light" aria-label="后一天" @click="emit('next-day')">
        <FontAwesomeIcon icon="chevron-right" aria-hidden="true" />
      </button>
      <button class="rounded-lg border border-primary-200 bg-primary-50 px-3 py-1.5 text-xs font-bold text-primary-700" @click="emit('today')">今天</button>
    </div>

    <span class="flex-1" />

    <button data-test="open-entry" class="rounded-lg bg-primary-600 px-3.5 py-2 text-xs font-bold text-white" @click="emit('open-entry')">
      <FontAwesomeIcon icon="plus" class="mr-1" aria-hidden="true" /> 录入
    </button>
    <button class="rounded-lg border border-border-light px-3.5 py-2 text-xs font-semibold" @click="emit('export')">导出</button>
    <button data-test="open-records" class="rounded-lg border border-border-light px-3.5 py-2 text-xs font-semibold" @click="emit('open-records')">明细</button>
  </header>
</template>

<script setup lang="ts">
defineProps<{ date: string }>()

const emit = defineEmits<{
  'update:date': [value: string]
  'prev-day': []
  'next-day': []
  today: []
  'open-entry': []
  'open-records': []
  export: []
}>()
</script>
