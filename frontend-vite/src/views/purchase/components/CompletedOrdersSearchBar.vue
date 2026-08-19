<template>
  <!-- 快速筛选 -->
  <div v-if="quickFilters.length > 0" class="coq-quick">
    <button
      v-for="f in quickFilters"
      :key="f.id"
      :class="['coq-quick-btn', currentQuickFilterId === f.id ? 'coq-quick-active' : '']"
      @click="$emit('applyQuickFilter', f.id)"
    >
      {{ f.name }}
    </button>
  </div>

  <!-- 搜索栏（内联，无背景框） -->
  <div class="coq-search">
    <div class="coq-search-grid">
      <div class="coq-search-cell">
        <FontAwesomeIcon icon="hashtag" class="coq-search-icon" aria-hidden="true" />
        <input
          type="text"
          class="coq-search-input"
          placeholder="订单号"
          :value="filters.order_no"
          @input="$emit('updateFilter', { key: 'order_no', value: ($event.target as HTMLInputElement).value })"
          @keyup.enter="$emit('search')"
        />
      </div>
      <div class="coq-search-cell">
        <FontAwesomeIcon icon="user" class="coq-search-icon" aria-hidden="true" />
        <input
          type="text"
          class="coq-search-input"
          placeholder="客户名称"
          :value="filters.customer_name"
          @input="$emit('updateFilter', { key: 'customer_name', value: ($event.target as HTMLInputElement).value })"
          @keyup.enter="$emit('search')"
        />
      </div>
      <div class="coq-search-cell">
        <FontAwesomeIcon icon="box" class="coq-search-icon" aria-hidden="true" />
        <input
          type="text"
          class="coq-search-input"
          placeholder="产品名称"
          :value="filters.product_name"
          @input="$emit('updateFilter', { key: 'product_name', value: ($event.target as HTMLInputElement).value })"
          @keyup.enter="$emit('search')"
        />
      </div>
      <div class="coq-search-cell coq-search-date">
        <UiDatePicker
          :model-value="filters.start_date"
          placeholder="开始日期"
          @update:model-value="$emit('updateFilter', { key: 'start_date', value: $event })"
        />
      </div>
      <div class="coq-search-sep">~</div>
      <div class="coq-search-cell coq-search-date">
        <UiDatePicker
          :model-value="filters.end_date"
          placeholder="结束日期"
          @update:model-value="$emit('updateFilter', { key: 'end_date', value: $event })"
        />
      </div>
      <button class="coq-btn coq-btn-primary coq-search-go" @click="$emit('search')" aria-label="查询">
        <FontAwesomeIcon icon="search" aria-hidden="true" />
        <span>查询</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import type { QuickFilter } from '../composables/useCompletedOrders'

defineProps<{
  filters: Record<string, string>
  quickFilters: QuickFilter[]
  currentQuickFilterId: string | null
}>()

defineEmits<{
  updateFilter: [payload: { key: string; value: string }]
  search: []
  applyQuickFilter: [id: string]
}>()
</script>

<style scoped>
.coq-quick {
  display: flex;
  gap: 4px;
  padding: 0 24px 12px;
  flex-wrap: wrap;
}

.coq-quick-btn {
  padding: 4px 12px;
  border: 1px solid var(--coq-border);
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
  background: var(--coq-bg);
  color: var(--coq-slate);
  font-family: inherit;
}

.coq-quick-btn:hover {
  border-color: var(--coq-blue);
  color: var(--coq-navy);
}

.coq-quick-active {
  background: var(--coq-navy) !important;
  border-color: var(--coq-navy) !important;
  color: #fff !important;
}

.coq-search {
  padding: 0 24px 12px;
  border-bottom: 1px solid var(--coq-border);
}

.coq-search-grid {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.coq-search-cell {
  position: relative;
  min-width: 150px;
}

.coq-search-date {
  min-width: 140px;
}

.coq-search-icon {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--coq-text-muted);
  font-size: 11px;
  pointer-events: none;
  z-index: 1;
}

.coq-search-input {
  width: 100%;
  padding: 7px 12px 7px 30px;
  border: 1px solid var(--coq-border);
  border-radius: 6px;
  font-size: 13px;
  outline: none;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
  background: var(--coq-bg);
  font-family: inherit;
  color: var(--coq-text);
  box-sizing: border-box;
}

.coq-search-input::placeholder {
  color: var(--coq-text-muted);
}

.coq-search-input:focus {
  border-color: var(--coq-blue);
  box-shadow: 0 0 0 3px rgba(91, 141, 239, 0.12);
}

.coq-search-sep {
  color: var(--coq-text-muted);
  font-size: 13px;
  padding: 0 2px;
}

.coq-search-go {
  margin-left: auto;
}

.coq-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1px solid var(--coq-border);
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
  background: var(--coq-bg);
  color: var(--coq-text-secondary);
  white-space: nowrap;
  font-family: inherit;
  line-height: 1.4;
}

.coq-btn i {
  font-size: 11px;
}

.coq-btn:hover {
  border-color: var(--coq-blue);
  color: var(--coq-navy);
  background: var(--coq-blue-light);
}

.coq-btn-primary {
  background: var(--coq-navy);
  border-color: var(--coq-navy);
  color: #fff;
}

.coq-btn-primary:hover {
  background: var(--coq-navy-deep);
  border-color: var(--coq-navy-deep);
  color: #fff;
}

@media (max-width: 768px) {
  .coq-search-grid {
    flex-direction: column;
    align-items: stretch;
  }

  .coq-search-cell {
    min-width: unset;
  }

  .coq-search-sep {
    display: none;
  }

  .coq-search-go {
    margin-left: 0;
  }
}
</style>