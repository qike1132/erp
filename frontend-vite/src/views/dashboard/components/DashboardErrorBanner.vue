<template>
  <div class="db-error-banner mb-4 p-3 rounded-[var(--radius-card)] bg-danger-50 border border-danger-200 flex items-center gap-3">
    <div class="w-7 h-7 rounded-[var(--radius-md)] bg-danger-100 flex items-center justify-center shrink-0">
      <FontAwesomeIcon icon="triangle-exclamation" class="text-danger-500 text-xs" />
    </div>
    <div class="flex-1 min-w-0">
      <p class="text-sm text-danger-700 font-medium">{{ message }}</p>
      <p class="text-xs text-danger-500 mt-0.5">{{ detail }}</p>
    </div>
    <button
      class="px-3 py-1.5 rounded-[var(--radius-button)] bg-danger-500 text-white text-xs font-semibold hover:bg-danger-600 transition-all duration-300 hover:-translate-y-0.5 shrink-0"
      @click="emit('retry')"
    >
      <FontAwesomeIcon icon="rotate-right" class="mr-1" />重试
    </button>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  message: string
  detail: string
}>()

const emit = defineEmits<{ 'retry': [] }>()
</script>

<style scoped>
.db-error-banner {
  animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>