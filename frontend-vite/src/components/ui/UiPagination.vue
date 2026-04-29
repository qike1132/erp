<template>
  <div class="inline-flex justify-center items-center gap-1 py-4">
    <button
      class="px-3 py-1.5 border border-border bg-white rounded-lg text-sm cursor-pointer transition-all duration-200 text-text hover:border-primary-500 hover:text-primary-500 disabled:opacity-40 disabled:cursor-not-allowed"
      :disabled="currentPage <= 1"
      @click="$emit('update:currentPage', currentPage - 1)"
    >
      <i class="fas fa-chevron-left" />
    </button>
    <button
      v-for="p in visiblePages"
      :key="p"
      :class="[
        'px-3 py-1.5 border rounded-lg text-sm cursor-pointer transition-all duration-200',
        p === currentPage
          ? 'bg-primary-500 text-white border-primary-500'
          : 'bg-white border-border text-text hover:border-primary-500 hover:text-primary-500',
      ]"
      @click="$emit('update:currentPage', p)"
    >
      {{ p }}
    </button>
    <button
      class="px-3 py-1.5 border border-border bg-white rounded-lg text-sm cursor-pointer transition-all duration-200 text-text hover:border-primary-500 hover:text-primary-500 disabled:opacity-40 disabled:cursor-not-allowed"
      :disabled="currentPage >= totalPages"
      @click="$emit('update:currentPage', currentPage + 1)"
    >
      <i class="fas fa-chevron-right" />
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  currentPage: number
  totalPages: number
  maxVisible?: number
}>()

defineEmits<{
  'update:currentPage': [page: number]
}>()

const maxShow = computed(() => props.maxVisible ?? 5)

const visiblePages = computed(() => {
  const total = props.totalPages
  const current = props.currentPage
  let start = Math.max(1, current - Math.floor(maxShow.value / 2))
  let end = Math.min(total, start + maxShow.value - 1)
  if (end - start < maxShow.value - 1) start = Math.max(1, end - maxShow.value + 1)
  const pages: number[] = []
  for (let i = start; i <= end; i++) pages.push(i)
  return pages
})
</script>
