<template>
  <div class="mc-filter-bar">
    <button
      v-for="f in options"
      :key="f.value"
      :class="['mc-filter-btn', modelValue === f.value ? 'active' : '']"
      @click="model = f.value"
    >
      {{ f.label }}
    </button>
  </div>
</template>

<script setup lang="ts">
type FilterValue = 'all' | 'true' | 'false'

const model = defineModel<FilterValue>({ default: 'all' })

defineProps<{
  options: Array<{ label: string; value: FilterValue }>
}>()
</script>

<style scoped>
.mc-filter-bar {
  display: flex;
  gap: 8px;
  padding: 0 16px 12px;
}

.mc-filter-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 9px 14px;
  background: white;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: border-color 0.2s ease, background 0.2s ease, transform 0.2s ease;
}

.mc-filter-btn:hover {
  background: white;
  border-color: var(--color-border, #cbd5e1);
  transform: translateY(-1px);
}

.mc-filter-btn.active {
  background: var(--color-primary-50);
  border-color: var(--color-primary-400);
  color: var(--color-primary-700);
}
</style>