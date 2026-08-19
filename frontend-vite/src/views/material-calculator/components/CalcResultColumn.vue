<template>
  <div class="mc-col mc-col-results">
    <div class="mc-col-title">
      <FontAwesomeIcon icon="chart-pie" aria-hidden="true" />
      物料用量计算结果
    </div>

    <div class="mc-result-content">
      <div v-if="!hasResults" class="mc-empty-state">
        <FontAwesomeIcon icon="calculator" aria-hidden="true" />
        <span>选择产品并输入数量后自动计算</span>
      </div>
      <div v-else>
        <div
          v-for="cat in categoryList"
          :key="cat.key"
          class="mc-category-block"
          :class="'mc-cat-' + cat.key"
        >
          <button class="mc-category-header" @click="collapsed[cat.key] = !collapsed[cat.key]" aria-label="{{ cat.label }} ({{ calcResults[cat.key]">
            <i :class="['mc-cat-icon', cat.icon]"  aria-hidden="true" />
            <span class="mc-cat-label">{{ cat.label }}</span>
            <span class="mc-cat-count">({{ calcResults[cat.key]?.length ?? 0 }} 项)</span>
            <FontAwesomeIcon icon="chevron-down" :class="['mc-cat-toggle', collapsed[cat.key] ? '' : 'expanded']" aria-hidden="true" />
          </button>

          <div v-if="!collapsed[cat.key] && calcResults[cat.key]?.length" class="mc-category-table">
            <UiDataTable
              :data="calcResults[cat.key] ?? []"
              :columns="calcColumns"
              row-key="material_name"
            >
              <template #column-body-supplier_name="{ row }">{{ (row as MaterialCalcRow).supplier_name || '-' }}</template>
              <template #column-body-material_name="{ row }">{{ (row as MaterialCalcRow).material_name }}</template>
              <template #column-body-specification="{ row }">{{ (row as MaterialCalcRow).specification || '-' }}</template>
              <template #column-body-total_quantity="{ row }">
                <span class="mc-qty-cell">{{ formatFillingQty(cat.key, row as MaterialCalcRow) }}</span>
              </template>
            </UiDataTable>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// 物料用量计算结果列（从 MaterialCalculatorView.vue 抽出，模板原样搬移）
import { reactive } from 'vue'
import type { MaterialCalcRow } from '@/api'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
import { CALC_CATEGORY_LIST } from '@/composables/useMaterialCalculator'

defineProps<{
  calcResults: Record<string, MaterialCalcRow[]>
  hasResults: boolean
}>()

// 分类折叠状态
const collapsed = reactive<Record<string, boolean>>({})

// 分类列表
const categoryList = CALC_CATEGORY_LIST

// 填充类总采购量按克自动换算为 kg：克/g → kg，其他单位原样显示
function formatFillingQty(catKey: string, row: MaterialCalcRow): string {
  if (catKey !== 'filling') return `${row.total_quantity} ${row.unit}`
  const unit = (row.unit || '').trim()
  if (unit === '克' || unit.toLowerCase() === 'g') {
    const kg = row.total_quantity / 1000
    // 最多保留 3 位小数，去掉尾随零
    const formatted = `${parseFloat(kg.toFixed(3))}`
    return `${formatted} kg`
  }
  return `${row.total_quantity} ${row.unit}`
}

/** UiDataTable 列定义 */
const calcColumns: TableColumn[] = [
  { field: 'supplier_name', header: '供应商', align: 'left' },
  { field: 'material_name', header: '物料名称', align: 'left' },
  { field: 'specification', header: '规格', align: 'left' },
  { field: 'total_quantity', header: '总采购量', align: 'right' },
]
</script>

<style scoped>
/* === Results === */
.mc-result-content {
  padding: 16px;
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}

.mc-category-block {
  margin-bottom: 16px;
}

.mc-category-header {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-radius: 11px;
  border: none;
  cursor: pointer;
  transition: background 0.3s ease;
  text-align: left;
}

.mc-cat-icon {
  font-size: 15px;
}

.mc-cat-label {
  font-size: 14px;
  font-weight: 700;
}

.mc-cat-count {
  font-size: 12px;
  color: var(--color-text-secondary);
}

.mc-cat-toggle {
  margin-left: auto;
  font-size: 11px;
  color: var(--color-text-muted, #94a3b8);
  transition: transform 0.25s ease;
}

.mc-cat-toggle.expanded {
  transform: rotate(180deg);
}

/* Category color variants */
.mc-cat-filling .mc-category-header {
  background: linear-gradient(135deg, var(--color-info-50), var(--color-surface-card));
}

.mc-cat-filling .mc-cat-icon,
.mc-cat-filling .mc-cat-label {
  color: var(--color-primary-700);
}

.mc-cat-fabric .mc-category-header {
  background: linear-gradient(135deg, var(--color-success-50), var(--color-surface-card));
}

.mc-cat-fabric .mc-cat-icon,
.mc-cat-fabric .mc-cat-label {
  color: var(--color-success-700);
}

.mc-cat-accessory .mc-category-header {
  background: linear-gradient(135deg, var(--color-warning-50), var(--color-surface-card));
}

.mc-cat-accessory .mc-cat-icon,
.mc-cat-accessory .mc-cat-label {
  color: var(--color-warning-800);
}

.mc-category-table {
  margin-top: 8px;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid var(--color-border-light, #e2e8f0);
}

.mc-qty-cell {
  text-align: right;
  font-weight: 600;
  white-space: nowrap;
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
