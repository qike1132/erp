<template>
  <div class="sk-toolbar">
    <div class="sk-title">
      <FontAwesomeIcon icon="warehouse" aria-hidden="true" />
      <h1>库存查询</h1>
    </div>

    <div class="sk-search">
      <FontAwesomeIcon icon="search" class="sk-search-icon" aria-hidden="true" />
      <input
        class="sk-search-input"
        :value="search"
        placeholder="输入产品名称或 69 码"
        aria-label="输入产品名称或 69 码"
        @input="emit('update:search', ($event.target as HTMLInputElement).value)"
        @keyup.enter="emit('search')"
      />
    </div>

    <InventoryStatRow v-if="hasData" :orders="orders" :stockin="stockin" />

    <button v-if="hasData" class="sk-export-btn" aria-label="导出" @click="emit('export')">
      <FontAwesomeIcon icon="file-excel" aria-hidden="true" />导出 Excel
    </button>
  </div>
</template>

<script setup lang="ts">
/**
 * InventoryToolbar.vue — 库存页单行工具条
 *
 * 把原先分散在两处的元素收进一行：卡片头的导出按钮、过滤栏的搜索与汇总。
 * 纯受控组件：搜索词由父级持有（父级另有防抖副本驱动查询），本组件不存状态。
 * 无数据时汇总与导出一并隐藏（一排 0 与空导出没有意义）。
 */
import InventoryStatRow from './InventoryStatRow.vue'

defineProps<{
  /** 搜索词（受控） */
  search: string
  /** 汇总：未发完的订单数量 */
  orders: number
  /** 汇总：已入库未消耗 */
  stockin: number
  /** 当前是否有可展示/可导出的数据 */
  hasData: boolean
}>()

const emit = defineEmits<{
  'update:search': [value: string]
  search: []
  export: []
}>()
</script>

<style scoped>
.sk-toolbar {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 10px 20px;
  min-height: 62px;
  border-bottom: 1px solid var(--color-border-light, #f0f2f5);
  flex-shrink: 0;
}
.sk-title {
  display: flex;
  align-items: center;
  gap: 9px;
  flex-shrink: 0;
}
.sk-title svg {
  width: 18px;
  height: 18px;
  color: var(--color-primary-600);
}
.sk-title h1 {
  font-size: 16px;
  font-weight: 700;
  color: var(--color-text);
  white-space: nowrap;
}
.sk-search {
  position: relative;
  flex-shrink: 0;
}
.sk-search-icon {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  width: 13px;
  height: 13px;
  color: var(--color-text-muted);
  pointer-events: none;
}
.sk-search-input {
  width: 230px;
  padding: 7px 12px 7px 30px;
  border: 1.5px solid var(--color-border);
  border-radius: 9px;
  background: white;
  font-size: 12.5px;
  font-family: inherit;
  color: var(--color-text);
  outline: none;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.sk-search-input::placeholder { color: var(--color-text-muted); }
.sk-search-input:focus {
  border-color: var(--color-primary-500);
  box-shadow: 0 0 0 3px rgba(91, 141, 239, 0.15);
}
.sk-search-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
/* 汇总与导出靠右；搜索与标题靠左 */
.sk-toolbar :deep(.sk-stat-row) { margin-left: auto; }
.sk-export-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  padding: 7px 14px;
  border: 1.5px solid var(--color-success-200);
  border-radius: 9px;
  background: white;
  font-family: inherit;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--color-success-600);
  white-space: nowrap;
  cursor: pointer;
  transition: background 0.2s ease, border-color 0.2s ease;
}
.sk-export-btn:hover {
  background: var(--color-success-50);
  border-color: var(--color-success-500);
}
@media (max-width: 980px) {
  .sk-toolbar {
    flex-wrap: wrap;
    gap: 10px;
    padding-bottom: 12px;
  }
  .sk-toolbar :deep(.sk-stat-row) {
    order: 10;
    width: 100%;
    margin-left: 0;
    padding-top: 8px;
    border-top: 1px dashed var(--color-border-light);
  }
}
</style>
