<template>
  <div class="mc-col mc-col-orders">
    <div class="mc-col-title">
      <FontAwesomeIcon icon="clipboard-check" aria-hidden="true" />
      订单数量录入
    </div>

    <div class="mc-order-list">
      <div v-if="orderItems.length === 0" class="mc-empty-state">
        <FontAwesomeIcon icon="hand-point-left" aria-hidden="true" />
        <span>请从左侧选择产品</span>
      </div>
      <div v-for="item in orderItems" :key="item.product_id" class="mc-order-item">
        <div class="mc-order-name">
          {{ item.name }}
        </div>
        <div class="mc-order-inputs">
          <input
            type="number"
            class="form-number-input mc-qty-input"
            v-model.number="item.quantity"
            min="0"
            step="1"
            @input="emit('qty-input', item)"
          />
        </div>
        <button class="mc-delete-btn" @click="emit('remove', item.product_id)" aria-label="删除">
          <FontAwesomeIcon icon="trash-alt" aria-hidden="true" />
        </button>
      </div>
    </div>

    <div v-if="totalOrders > 0" class="mc-summary-panel">
      <span class="mc-summary-label">订单总数</span>
      <div class="mc-summary-value">
        <span class="mc-summary-number">{{ totalOrders }}</span>
        <span class="mc-summary-unit">件</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// 订单数量录入列（从 MaterialCalculatorView.vue 抽出，模板原样搬移）
defineProps<{
  orderItems: { product_id: number; name: string; quantity: number }[]
  totalOrders: number
}>()

const emit = defineEmits<{
  'qty-input': [item: { quantity: number }]
  remove: [productId: number]
}>()
</script>

<style scoped>
.form-number-input {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-size: 13px;
  color: var(--color-text);
  font-family: inherit;
  -moz-appearance: textfield;
}
.form-number-input::-webkit-inner-spin-button,
.form-number-input::-webkit-outer-spin-button {
  opacity: 1;
}
.form-number-input:focus {
  outline: none;
  border-color: var(--color-primary-500);
  box-shadow: 0 0 0 3px rgba(91, 141, 239, 0.15);
}
.form-number-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }

.mc-order-list {
  padding: 12px 16px;
  min-height: 60px;
  flex: 1;
  overflow-y: auto;
}

.mc-order-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  margin-bottom: 8px;
  background: white;
  transition: border-color 0.3s ease, transform 0.3s ease, box-shadow 0.3s ease;
}

.mc-order-item:hover {
  border-color: var(--color-primary-300);
  transform: translateY(-1px);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}

.mc-order-name {
  flex: 1;
  font-weight: 650;
  font-size: 14px;
  color: var(--color-text);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mc-order-inputs {
  display: flex;
  gap: 8px;
  align-items: center;
}

.mc-qty-input {
  width: 110px;
}

.mc-delete-btn {
  background: none;
  border: none;
  color: var(--color-text-muted, #94a3b8);
  cursor: pointer;
  padding: 8px;
  border-radius: 8px;
  transition: background 0.2s, color 0.2s;
  font-size: 13px;
}

.mc-delete-btn:hover {
  background: var(--color-danger-50);
  color: var(--color-danger-500);
}

/* === Summary Panel === */
.mc-summary-panel {
  margin: 0 16px 12px;
  padding: 10px 14px;
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  border-radius: 13px;
  border: 1px solid var(--color-primary-200);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.mc-summary-label {
  font-size: 13px;
  color: var(--color-text-secondary);
  font-weight: 500;
}

.mc-summary-value {
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.mc-summary-number {
  font-size: 32px;
  font-weight: 800;
  color: var(--color-primary-600);
  line-height: 1;
}

.mc-summary-unit {
  font-size: 14px;
  color: var(--color-primary-500);
  font-weight: 500;
}

/* === Empty State === */
.mc-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-text-muted, #94a3b8);
  font-size: 14px;
}

.mc-empty-state i {
  font-size: 28px;
  opacity: 0.5;
}
</style>
