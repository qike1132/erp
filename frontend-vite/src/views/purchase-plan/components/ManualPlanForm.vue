<template>
  <div>
    <div class="csd-detail-header">
      <span class="csd-field-cust">客户 <span class="csd-required">*</span></span>
      <span class="csd-field-flex">产品名称 <span class="csd-required">*</span></span>
      <span class="csd-field-xs">数量 <span class="csd-required">*</span></span>
      <span class="csd-field-sm">出货日期 <span class="csd-required">*</span></span>
      <span class="csd-field-action" />
    </div>
    <div v-for="(d, idx) in details" :key="idx" class="csd-detail-item">
      <div class="csd-detail-row">
        <div class="csd-field csd-field-cust">
          <UiSelect
            v-model="d.customer_id"
            placeholder="选择客户"
            :options="customerOptions"
            style="width: 100%"
          />
        </div>
        <div class="csd-field csd-field-flex csd-field-product">
          <input
            v-model="d.product_name"
            type="text"
            class="csd-input"
            placeholder="输入产品名称"
            @input="emit('product-input', idx)"
            @focus="emit('product-focus', idx)"
            @blur="emit('product-blur', idx)"
          />
          <div v-if="d._showSuggest && productSuggestions[idx]?.length" class="csd-suggest-list">
            <div
              v-for="p in productSuggestions[idx]"
              :key="p.id"
              class="csd-suggest-item"
              @mousedown.prevent="emit('select-product', idx, p)"
            >
              <span class="csd-suggest-name">{{ p.name }}</span>
              <span class="csd-suggest-meta">
                <span v-if="p.barcode" class="csd-suggest-barcode">{{ p.barcode }}</span>
                <span v-if="p.current_stock != null" class="csd-suggest-stock">库存 {{ p.current_stock }}</span>
              </span>
            </div>
          </div>
        </div>
        <div class="csd-field csd-field-xs">
          <input
            v-model.number="d.quantity"
            type="number"
            class="csd-input csd-input-num"
            min="1"
            placeholder="0"
          />
        </div>
        <div class="csd-field csd-field-sm">
          <input
            type="date"
            class="csd-input csd-input-date"
            :value="d.plan_date"
            @input="d.plan_date = ($event.target as HTMLInputElement).value"
            @click="($event.target as HTMLInputElement).showPicker()"
          />
        </div>
        <button
          v-if="details.length > 1"
          class="csd-remove-btn"
          title="移除此行"
          @click="emit('remove', idx)"
        >
          <FontAwesomeIcon icon="trash" aria-hidden="true" />
        </button>
      </div>
    </div>
    <div v-if="errorMsg" class="csd-error">
      <FontAwesomeIcon icon="exclamation-circle" aria-hidden="true" /> {{ errorMsg }}
    </div>
  </div>
</template>

<script setup lang="ts">
// 出货计划「填写数据」明细表单（从 CreateShipmentPlanDialog.vue 抽出，模板原样搬移；SKU 建议选择器重组块）
import UiSelect from '@/components/ui/UiSelect.vue'
import type { DetailLine, ProductSuggestion } from '../composables/useCreateShipmentPlan'

defineProps<{
  details: DetailLine[]
  customerOptions: { value: string; label: string }[]
  productSuggestions: Record<number, ProductSuggestion[]>
  errorMsg: string
}>()

const emit = defineEmits<{
  remove: [idx: number]
  'product-input': [idx: number]
  'product-focus': [idx: number]
  'product-blur': [idx: number]
  'select-product': [idx: number, p: ProductSuggestion]
}>()
</script>

<style scoped>
.csd-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.csd-required {
  color: var(--color-danger-500);
}

.csd-input {
  padding: 0 10px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: var(--radius-input, 12px);
  font-size: 0.9375rem;
  line-height: 1.5;
  outline: none;
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
  background: white;
  width: 100%;
  box-sizing: border-box;
  color: var(--color-text);
  height: 44px;
}
.csd-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.csd-input:focus {
  border-color: var(--color-primary-400);
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.csd-input::placeholder {
  color: var(--color-text-muted);
  font-size: 14px;
  font-weight: 400;
  opacity: 1;
}

.csd-input-num {
  text-align: center;
  font-weight: 700;
}

.csd-input-date {
  cursor: pointer;
}

.csd-detail-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 10px 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-muted);
}

.csd-detail-header span {
  display: flex;
  align-items: center;
}

.csd-field-product {
  position: relative;
}

.csd-suggest-list {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  z-index: 100;
  background: white;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.1);
  margin-top: 4px;
  max-height: 200px;
  overflow-y: auto;
}

.csd-suggest-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  cursor: pointer;
  transition: background 0.15s ease;
  font-size: 13px;
  gap: 8px;
}

.csd-suggest-item:hover {
  background: var(--color-primary-50);
}

.csd-suggest-item:first-child {
  border-radius: 10px 10px 0 0;
}

.csd-suggest-item:last-child {
  border-radius: 0 0 10px 10px;
}

.csd-suggest-name {
  font-weight: 500;
  color: var(--color-text);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.csd-suggest-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.csd-suggest-barcode {
  font-size: 11px;
  color: var(--color-text-muted);
  font-family: var(--font-mono, monospace);
  background: var(--color-surface);
  padding: 2px 6px;
  border-radius: 4px;
}

.csd-suggest-stock {
  font-size: 11px;
  color: var(--color-success-600);
  font-weight: 500;
}

.csd-field-action {
  width: 44px;
  flex-shrink: 0;
}

.csd-detail-item {
  padding: 6px 10px;
  background: transparent;
  border: none;
  border-radius: 8px;
}

.csd-detail-row {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  flex-wrap: nowrap;
}

.csd-field-flex {
  flex: 1;
  min-width: 160px;
}

.csd-field-cust {
  width: 180px;
  flex-shrink: 0;
}

.csd-field-sm {
  width: 140px;
  flex-shrink: 0;
}

.csd-field-xs {
  width: 90px;
  flex-shrink: 0;
}

.csd-remove-btn {
  width: 44px;
  height: 44px;
  border-radius: 9px;
  border: 1px solid var(--color-danger-200);
  background: white;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-danger-500);
  font-size: 0.75rem;
  transition: background 0.2s ease, border-color 0.2s ease, color 0.2s ease;
  flex-shrink: 0;
}
.csd-remove-btn:hover {
  background: var(--color-danger-50);
  border-color: var(--color-danger-400);
  color: var(--color-danger-600);
}

.csd-error {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 10px;
  background: var(--color-danger-50);
  color: var(--color-danger-600);
  font-size: 13px;
  font-weight: 600;
  border: 1px solid var(--color-danger-200);
}
</style>
