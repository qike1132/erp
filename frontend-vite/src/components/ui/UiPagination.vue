<template>
  <div class="ui-pagination">
    <button class="ui-page-btn" :disabled="currentPage <= 1" @click="$emit('update:currentPage', 1)">
      <i class="fas fa-angle-double-left" />
    </button>
    <button class="ui-page-btn" :disabled="currentPage <= 1" @click="$emit('update:currentPage', currentPage - 1)">
      <i class="fas fa-angle-left" />
    </button>
    <span class="ui-page-info">{{ currentPage }} / {{ totalPages }}</span>
    <button class="ui-page-btn" :disabled="currentPage >= totalPages" @click="$emit('update:currentPage', currentPage + 1)">
      <i class="fas fa-angle-right" />
    </button>
    <button class="ui-page-btn" :disabled="currentPage >= totalPages" @click="$emit('update:currentPage', totalPages)">
      <i class="fas fa-angle-double-right" />
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
  transition: all 0.2s;
}
.ui-page-btn:hover:not(:disabled) {
  border-color: var(--color-primary-300);
  color: var(--color-primary-600);
}
.ui-page-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.ui-page-info {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
  min-width: 80px;
  text-align: center;
}
.ui-page-total {
  font-size: 12px;
  color: var(--color-text-secondary);
  margin-left: 8px;
}
</style>
