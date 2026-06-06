<template>
  <div role="alert" :class="['rounded-lg px-4 py-3 flex items-start gap-3', variantClass]">
    <i :class="[iconClass, 'mt-0.5']" aria-hidden="true" />
    <div class="flex-1 min-w-0 text-sm">
      <div v-if="title" class="font-semibold mb-0.5">
        {{ title }}
      </div>
      <div><slot /></div>
    </div>
    <button
      v-if="closable"
      class="text-current opacity-50 hover:opacity-100 transition-opacity"
      aria-label="关闭"
      @click="$emit('close')"
    >
      <i class="fas fa-times text-sm" aria-hidden="true" />
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  variant?: 'info' | 'success' | 'warning' | 'danger'
  title?: string
  closable?: boolean
}>()

defineEmits<{ close: [] }>()

const variantClass = computed(() => {
  switch (props.variant) {
    case 'success':
      return 'bg-success-50 text-success-700 border border-success-200'
    case 'warning':
      return 'bg-warning-50 text-warning-700 border border-warning-200'
    case 'danger':
      return 'bg-danger-50 text-danger-700 border border-danger-200'
    default:
      return 'bg-primary-50 text-primary-700 border border-primary-200'
  }
})

const iconClass = computed(() => {
  switch (props.variant) {
    case 'success':
      return 'fas fa-check-circle'
    case 'warning':
      return 'fas fa-exclamation-triangle'
    case 'danger':
      return 'fas fa-times-circle'
    default:
      return 'fas fa-info-circle'
  }
})
</script>
