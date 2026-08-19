<template>
  <div class="co-type-switch">
    <button :class="['co-type-btn', isOrder && 'active']" @click="form.type = 'order'" aria-label="订单">
      <FontAwesomeIcon icon="clipboard-list" aria-hidden="true" />订单
    </button>
    <button :class="['co-type-btn', !isOrder && 'active']" @click="form.type = 'stockin'" aria-label="备货">
      <FontAwesomeIcon icon="truck-loading" aria-hidden="true" />备货
    </button>
  </div>
</template>

<script setup lang="ts">
import type { FormState } from '../composables/types'

defineProps<{
  isOrder: boolean
}>()

const form = defineModel<FormState>('form', { required: true })
</script>

<style scoped>
.co-type-switch {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
}
.co-type-btn {
  padding: 5px 14px;
  border: none;
  border-radius: 9px;
  background: transparent;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.3s ease, color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--color-text-secondary);
}
.co-type-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}
.co-type-btn.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91, 141, 239, 0.2);
  transform: translateY(-1px);
}
</style>