<template>
  <div class="ui-pagination">
    <button class="ui-page-btn" :disabled="currentPage <= 1" aria-label="首页" @click="$emit('update:currentPage', 1)">
      <i class="fas fa-angle-double-left" aria-hidden="true" />
    </button>
    <button class="ui-page-btn" :disabled="currentPage <= 1" aria-label="上一页" @click="$emit('update:currentPage', currentPage - 1)">
      <i class="fas fa-angle-left" aria-hidden="true" />
    </button>
    <span class="ui-page-info">{{ currentPage }} / {{ totalPages }}</span>
    <button class="ui-page-btn" :disabled="currentPage >= totalPages" aria-label="下一页" @click="$emit('update:currentPage', currentPage + 1)">
      <i class="fas fa-angle-right" aria-hidden="true" />
    </button>
    <button class="ui-page-btn" :disabled="currentPage >= totalPages" aria-label="末页" @click="$emit('update:currentPage', totalPages)">
      <i class="fas fa-angle-double-right" aria-hidden="true" />
    </button>
    <span v-if="totalItems != null" class="ui-page-total">共 {{ totalItems }} 条</span>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  currentPage: number
  totalPages: number
  totalItems?: number
}>()

defineEmits<{
  'update:currentPage': [page: number]
}>()
</script>

<style scoped>
.ui-pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 16px 24px;
  border-top: 1px solid var(--color-border-light, #f1f5f9);
}
.ui-page-btn {
  padding: 6px 10px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 6px;
  background: white;
  cursor: pointer;
  font-size: 12px;
  color: var(--color-text-secondary);
  transition: border-color 0.2s, color 0.2s;
}
.ui-page-btn:hover:not(:disabled) {
  border-color: var(--color-primary-300);
  color: var(--color-primary-600);
}
.ui-page-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.ui-page-btn:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.ui-page-info {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
  min-width: 80px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}
.ui-page-total {
  font-size: 12px;
  color: var(--color-text-secondary);
  margin-left: 8px;
  font-variant-numeric: tabular-nums;
}
</style>
