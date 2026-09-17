<template>
  <div class="mc-col mc-col-orders">
    <div class="mc-col-title">
      <FontAwesomeIcon icon="clipboard-check" aria-hidden="true" />
      订单数量录入
      <span v-if="totalOrders > 0" class="mc-col-tail">合计 <b>{{ totalOrders }}</b> 件</span>
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
        <input
          v-model.number="item.quantity"
          type="number"
          class="form-number-input mc-qty-input"
          min="0"
          step="1"
          aria-label="订单数量"
          @input="emit('qty-input', item)"
        />
        <button class="mc-delete-btn" aria-label="删除" @click="emit('remove', item.product_id)">
          <FontAwesomeIcon icon="trash-alt" aria-hidden="true" />
        </button>
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
  height: 28px;
  padding: 0 8px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
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
  border-color: var(--color-primary-400);
  box-shadow: 0 0 0 3px rgba(91, 141, 239, 0.15);
}

.mc-order-list {
  padding: 8px 12px;
  min-height: 60px;
  flex: 1;
  overflow-y: auto;
}

/* 行高 63 → 44px（步长 71 → 48），与左列同一套节奏 */
.mc-order-item {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 44px;
  padding: 0 8px;
  border: 1px solid var(--color-border-light);
  border-radius: 6px;
  margin-bottom: 4px;
  background: #fff;
  transition: border-color 0.15s ease;
}

.mc-order-item:hover {
  border-color: var(--color-border);
}

.mc-order-name {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mc-qty-input {
  width: 84px;
  flex-shrink: 0;
  text-align: right;
}

.mc-delete-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  flex-shrink: 0;
  padding: 0;
  border: none;
  border-radius: 4px;
  background: none;
  color: var(--color-text-muted);
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.mc-delete-btn svg {
  width: 12px;
  height: 12px;
}

.mc-delete-btn:hover {
  background: var(--color-danger-50);
  color: var(--color-danger-500);
}

/* === Empty State === */
.mc-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 40px 20px;
  color: var(--color-text-muted);
  font-size: 13px;
}

.mc-empty-state svg {
  width: 26px;
  height: 26px;
  opacity: 0.4;
}
</style>
