<template>
  <div v-if="customers.length" class="sk-customer-bar">
    <div class="sk-customer-bar-inner">
      <span class="sk-customer-bar-label"><FontAwesomeIcon icon="users" aria-hidden="true" /> 客户</span>
      <div class="sk-customer-scroll">
        <button
          type="button"
          :class="['sk-customer-chip', { active: !selected }]"
          @click="$emit('select', '')"
        >
          <FontAwesomeIcon icon="th-large" aria-hidden="true" />全部
        </button>
        <button
          type="button"
          v-for="c in customers"
          :key="c"
          :class="['sk-customer-chip', { active: selected === c }]"
          @click="$emit('select', c)"
        >{{ c }}</button>
      </div>
      <Transition name="sk-bar-fade">
        <div v-if="loading" class="sk-customer-loading">
          <FontAwesomeIcon icon="circle-notch" class="fa-spin" aria-hidden="true" />
        </div>
      </Transition>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  customers: string[];
  selected: string;
  loading: boolean;
}>();

defineEmits<{ select: [name: string] }>();
</script>

<style scoped>
.sk-customer-bar {
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  background: linear-gradient(to bottom, var(--color-surface, #f8fafc), white);
}
.sk-customer-bar-inner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 24px;
  position: relative;
}
.sk-customer-bar-label {
  font-size: 12px;
  font-weight: 700;
  color: var(--color-text-secondary);
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 5px;
  flex-shrink: 0;
}
.sk-customer-bar-label i { color: var(--color-primary-500); font-size: 13px; }
.sk-customer-scroll {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  overflow-y: hidden;
  flex: 1;
  min-height: 0;
  padding: 2px 0;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
}
.sk-customer-scroll::-webkit-scrollbar { display: none; }
.sk-customer-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 16px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  border: 2px solid var(--color-border-light, #e2e8f0);
  background: white;
  color: var(--color-text-secondary);
  white-space: nowrap;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  user-select: none;
  font-family: inherit;
  line-height: inherit;
  flex-shrink: 0;
  position: relative;
}
.sk-customer-chip i { font-size: 11px; transition: transform 0.25s ease; }
.sk-customer-chip:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-600);
  background: var(--color-primary-50);
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}
.sk-customer-chip:hover i { transform: scale(1.15); }
.sk-customer-chip.active {
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700));
  color: white;
  border-color: transparent;
  box-shadow: 0 3px 12px rgba(59, 130, 246, 0.35);
  transform: translateY(-1px);
}
.sk-customer-chip.active:hover {
  background: linear-gradient(135deg, var(--color-primary-600), var(--color-primary-800));
  box-shadow: 0 4px 16px rgba(59, 130, 246, 0.4);
}
.sk-customer-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-primary-500);
  font-size: 14px;
  flex-shrink: 0;
  padding: 0 4px;
}
.sk-bar-fade-enter-active { transition: opacity 0.2s ease; }
.sk-bar-fade-leave-active { transition: opacity 0.15s ease; }
.sk-bar-fade-enter-from,
.sk-bar-fade-leave-to { opacity: 0; }
@media (max-width: 900px) {
  .sk-customer-bar-inner { padding: 8px 12px; gap: 8px; }
  .sk-customer-bar-label { display: none; }
  .sk-customer-chip { padding: 5px 12px; font-size: 11px; }
}
</style>