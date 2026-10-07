<template>
  <div class="sk-toolbar">
    <InventoryStatRow v-if="hasData" :orders="orders" :stockin="stockin" />

    <SearchBox
      :model-value="search"
      @update:model-value="emit('update:search', $event)"
      @search="emit('search')"
    />

    <button v-if="hasData" class="sk-export-btn" aria-label="导出" @click="emit('export')">
      <FontAwesomeIcon icon="file-excel" aria-hidden="true" />导出 Excel
    </button>
  </div>
</template>

<script setup lang="ts">
/**
 * InventoryToolbar.vue — 库存页单行工具条
 *
 * 布局（2026-10-07 调整）：三格汇总靠左，搜索框 + 导出按钮靠右。
 * 原「库存查询」标题与仓库图标已按业务要求移除（该页现为库存汇总，
 * 「库存查询」已并入本页的「库存」列）。
 * 搜索框已抽为共享组件 SearchBox。
 * 纯受控组件：搜索词由父级持有（父级另有防抖副本驱动查询），本组件不存状态。
 * 无数据时汇总与导出一并隐藏（一排 0 与空导出没有意义）。
 */
import SearchBox from '@/components/ui/SearchBox.vue'
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
/* 汇总靠左；搜索 + 导出靠右（margin-left:auto 把这一组推到右侧）。
   搜索框是子组件，其根节点带父级 scope 属性，故可在此命中。 */
.sk-toolbar > .sb-search {
  margin-left: auto;
}
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
