<template>
  <div class="ap-filter-bar">
    <UiSearchInput v-model="searchTerm" placeholder="搜索类型或摘要..." @search="emit('search')" @clear="emit('clear')" />
    <div class="ap-filter-group">
      <button
        v-for="opt in statusOptions"
        :key="opt.value"
        :class="['ap-filter-btn', { active: statusFilter === opt.value }]"
        @click="emit('update:statusFilter', opt.value)"
      >
        {{ opt.label }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import UiSearchInput from '@/components/ui/UiSearchInput.vue'

defineProps<{
  statusOptions: readonly { value: string; label: string }[]
}>()

const searchTerm = defineModel<string>('searchTerm', { default: '' })
const statusFilter = defineModel<string>('statusFilter', { default: '' })

const emit = defineEmits<{
  search: []
  clear: []
  'update:statusFilter': [value: string]
}>()
</script>

<style scoped>
.ap-filter-bar {
  display: flex;
  gap: 12px;
  padding: 12px 24px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  align-items: center;
}
.ap-filter-group {
  display: flex;
  gap: 8px;
}
.ap-filter-btn {
  padding: 7px 14px;
  background: var(--color-surface, #f8fafc);
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: border-color 0.2s ease, color 0.2s ease, background 0.2s ease, transform 0.2s ease;
  color: var(--color-text-secondary);
}
.ap-filter-btn:hover {
  transform: translateY(-1px);
}
.ap-filter-btn.active {
  background: var(--color-primary-50);
  border-color: var(--color-primary-400);
  color: var(--color-primary-700);
}
</style>