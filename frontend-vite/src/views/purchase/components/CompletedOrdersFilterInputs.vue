<template>
  <label class="pc-filter-input-wrap pc-filter-sm">
    <FontAwesomeIcon icon="hashtag" class="pc-filter-input-icon" aria-hidden="true" />
    <input
      v-model="draft.order_no"
      class="pc-filter-input"
      type="text"
      placeholder="订单号"
      autocomplete="off"
      @keyup.enter="$emit('search')"
    />
  </label>
  <label class="pc-filter-input-wrap pc-filter-sm">
    <FontAwesomeIcon icon="user" class="pc-filter-input-icon" aria-hidden="true" />
    <input
      v-model="draft.customer_name"
      class="pc-filter-input"
      type="text"
      placeholder="客户名称"
      autocomplete="off"
      @keyup.enter="$emit('search')"
    />
  </label>
  <label class="pc-filter-input-wrap">
    <FontAwesomeIcon icon="box" class="pc-filter-input-icon" aria-hidden="true" />
    <input
      v-model="draft.product_name"
      class="pc-filter-input"
      type="text"
      placeholder="产品名称"
      autocomplete="off"
      @keyup.enter="$emit('search')"
    />
  </label>
  <span class="pc-filter-date">
    <UiDatePicker v-model="draft.start_date" label="完成日期从" />
  </span>
  <span class="pc-filter-date">
    <UiDatePicker v-model="draft.end_date" label="完成日期到" />
  </span>
</template>

<script setup lang="ts">
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import type { CompletedOrderFilters } from '../composables/useCompletedOrders'

/**
 * 下单查询的筛选输入控件。
 *
 * 多根节点：不自己包一层容器，由父级 .pc-header-filters 统一 flex 排布，
 * 与「查询/重置/导出」按钮同处一行。
 */
const draft = defineModel<CompletedOrderFilters>('draft', { required: true })

defineEmits<{ search: [] }>()
</script>

<style scoped>
.pc-filter-input-wrap {
  position: relative;
  display: inline-flex;
  align-items: center;
  width: 220px;
}

/* 订单号/客户名称比产品名称短：收窄宽度，避免 5 个控件把表头挤成多行 */
.pc-filter-input-wrap.pc-filter-sm {
  width: 160px;
}

.pc-filter-date {
  display: inline-flex;
  width: 150px;
}

/* UiDatePicker 默认 44px 高 / 2px 边框，与同行的文本输入框（34px）不齐 */
.pc-filter-date :deep(.date-input) {
  height: 34px;
  min-height: 34px;
  padding: 0 30px 0 10px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  font-size: 13px;
  background: #fff;
}

.pc-filter-input-icon {
  position: absolute;
  left: 11px;
  font-size: 12px;
  color: var(--color-text-muted);
  pointer-events: none;
  transition: color 0.15s ease;
}

.pc-filter-input {
  width: 100%;
  height: 34px;
  padding: 0 12px 0 30px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  font-size: 13px;
  font-family: inherit;
  color: var(--color-text);
  background: #fff;
  outline: none;
  box-sizing: border-box;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.pc-filter-input:focus {
  border-color: var(--color-primary-500, #5b8def);
  box-shadow: 0 0 0 3px rgba(91, 141, 239, 0.14);
}

.pc-filter-input-wrap:focus-within .pc-filter-input-icon {
  color: var(--color-primary-500, #5b8def);
}

.pc-filter-input::placeholder {
  color: var(--color-text-muted);
}
</style>
