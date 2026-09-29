<template>
  <div v-if="customers.length" class="sk-customer-row">
    <span class="sk-customer-label">
      <FontAwesomeIcon icon="users" aria-hidden="true" /> 客户
    </span>
    <div class="sk-chip-scroll">
      <button
        type="button"
        :class="['sk-chip', { active: !selected }]"
        @click="$emit('select', '')"
      >
        <FontAwesomeIcon icon="th-large" aria-hidden="true" />全部
      </button>
      <button
        v-for="c in customers"
        :key="c"
        type="button"
        :class="['sk-chip', { active: selected === c }]"
        @click="$emit('select', c)"
      >{{ c }}</button>
    </div>
    <Transition name="sk-bar-fade">
      <span v-if="loading" class="sk-customer-loading">
        <FontAwesomeIcon icon="circle-notch" spin aria-hidden="true" />
      </span>
    </Transition>
  </div>
</template>

<script setup lang="ts">
/**
 * InventoryCustomerBar.vue — 客户筛选行（独立成一整行）
 *
 * 客户 chips 与搜索框分属两行：chips 数量随客户数增长，挤在搜索旁边会把
 * 汇总数字与导出按钮压变形，独立成行后可横向滚动而不影响其它元素。
 */
defineProps<{
  customers: string[]
  selected: string
  loading: boolean
}>()

defineEmits<{ select: [name: string] }>()
</script>

<style scoped>
.sk-customer-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 20px;
  border-bottom: 1px solid var(--color-border-light, #f0f2f5);
  background: linear-gradient(to bottom, var(--color-surface, #f8fafc), white);
  flex-shrink: 0;
}
.sk-customer-label {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-shrink: 0;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--color-text-secondary);
  white-space: nowrap;
}
.sk-customer-label svg {
  width: 12px;
  height: 12px;
  color: var(--color-primary-500);
}
.sk-chip-scroll {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  overflow-y: hidden;
  flex: 1;
  min-width: 0;
  padding: 2px 0;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
}
.sk-chip-scroll::-webkit-scrollbar { display: none; }
.sk-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex-shrink: 0;
  padding: 5px 14px;
  border: 1.5px solid var(--color-border);
  border-radius: 999px;
  background: white;
  font-family: inherit;
  font-size: 12px;
  font-weight: 600;
  line-height: inherit;
  color: var(--color-text-secondary);
  white-space: nowrap;
  cursor: pointer;
  user-select: none;
  transition: all 0.2s ease;
}
.sk-chip svg { width: 11px; height: 11px; }
.sk-chip:hover {
  border-color: var(--color-primary-500);
  color: var(--color-primary-600);
}
.sk-chip.active {
  background: var(--color-primary-600);
  border-color: var(--color-primary-600);
  color: white;
}
.sk-customer-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  padding: 0 4px;
  font-size: 13px;
  color: var(--color-primary-500);
}
.sk-bar-fade-enter-active { transition: opacity 0.2s ease; }
.sk-bar-fade-leave-active { transition: opacity 0.15s ease; }
.sk-bar-fade-enter-from,
.sk-bar-fade-leave-to { opacity: 0; }
@media (max-width: 900px) {
  .sk-customer-row { padding: 7px 12px; gap: 8px; }
  .sk-customer-label { display: none; }
}
</style>
