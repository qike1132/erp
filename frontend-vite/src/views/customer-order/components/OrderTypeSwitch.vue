<template>
  <div class="co-type-switch">
    <button :class="['co-type-btn', isOrder && 'active']" aria-label="订单" @click="form.type = 'order'">
      <FontAwesomeIcon icon="clipboard-list" aria-hidden="true" />订单
    </button>
    <button :class="['co-type-btn', !isOrder && 'active']" aria-label="备货" @click="form.type = 'stockin'">
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
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.co-type-btn {
  padding: 5px 14px;
  min-height: 32px;
  border: none;
  border-radius: 9px;
  background: transparent;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s ease, color 0.2s ease;
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--color-text-secondary);
}
.co-type-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}
.co-type-btn:focus-visible {
  outline: 2px solid var(--color-primary-500);
  outline-offset: 2px;
}
.co-type-btn.active {
  background: var(--color-primary-50);
  color: var(--color-primary-700);
  box-shadow: inset 0 0 0 1px var(--color-primary-200, var(--color-primary-100));
}
</style>