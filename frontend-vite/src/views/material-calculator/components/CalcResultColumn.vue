<template>
  <div class="mc-col mc-col-results">
    <div class="mc-col-title">
      <FontAwesomeIcon icon="chart-pie" aria-hidden="true" />
      物料用量计算结果
    </div>

    <div class="mc-result-content">
      <!-- 空态 -->
      <div v-if="!hasGroups && !hasResults" class="mc-empty-state">
        <FontAwesomeIcon icon="calculator" aria-hidden="true" />
        <span>选择产品并输入数量后自动计算</span>
      </div>

      <!-- 分块卡模式：每个作用域一张卡，默认 BOM 恒首块（顺序不动） -->
      <template v-else-if="hasGroups">
        <div
          v-for="(group, gi) in calcGroups"
          :key="groupKey(group)"
          class="mc-scope-card"
        >
          <div class="mc-scope-head">
            <span class="mc-scope-badge" :class="group.role_id == null ? 'is-default' : 'is-role'">
              {{ group.role_id == null ? '默认' : '#' + (gi + 1) }}
            </span>
            <span class="mc-scope-name">{{ groupName(group) }}</span>
            <span v-if="group.product_name" class="mc-scope-product">{{ group.product_name }}</span>
            <span class="mc-scope-qty">数量 {{ group.quantity }}</span>
          </div>

          <div
            v-for="cat in categoryList"
            :key="cat.key"
            class="mc-category-block"
            :class="'mc-cat-' + cat.key"
          >
            <button
              class="mc-category-header"
              :aria-label="`${cat.label} (${catRows(group, cat.key).length} 项)`"
              @click="toggle(groupKey(group), cat.key)"
            >
              <FontAwesomeIcon :icon="cat.icon" class="mc-cat-icon" aria-hidden="true" />
              <span class="mc-cat-label">{{ cat.label }}</span>
              <span class="mc-cat-count">({{ catRows(group, cat.key).length }} 项)</span>
              <FontAwesomeIcon
                icon="chevron-down"
                :class="['mc-cat-toggle', isCollapsed(groupKey(group), cat.key) ? '' : 'expanded']"
                aria-hidden="true"
              />
            </button>

            <div
              v-if="!isCollapsed(groupKey(group), cat.key) && catRows(group, cat.key).length"
              class="mc-category-table"
            >
              <UiDataTable :data="catRows(group, cat.key)" :columns="calcColumns" row-key="__rk">
                <template #column-body-supplier_name="{ row }">{{ (row as CalcRowVM).supplier_name || '-' }}</template>
                <template #column-body-material_name="{ row }">{{ (row as CalcRowVM).material_name }}</template>
                <template #column-body-specification="{ row }">{{ (row as CalcRowVM).specification || '-' }}</template>
                <template #column-body-total_quantity="{ row }">
                  <span class="mc-qty-cell">{{ formatFillingQty(cat.key, row as CalcRowVM) }}</span>
                </template>
              </UiDataTable>
            </div>
          </div>
        </div>
      </template>

      <!-- 扁平回退：旧后端 / groups 缺失时（A-5），行为与旧版一致 -->
      <template v-else>
        <div
          v-for="cat in categoryList"
          :key="cat.key"
          class="mc-category-block"
          :class="'mc-cat-' + cat.key"
        >
          <button
            class="mc-category-header"
            :aria-label="`${cat.label} (${flatRows(cat.key).length} 项)`"
            @click="toggle('flat', cat.key)"
          >
            <FontAwesomeIcon :icon="cat.icon" class="mc-cat-icon" aria-hidden="true" />
            <span class="mc-cat-label">{{ cat.label }}</span>
            <span class="mc-cat-count">({{ flatRows(cat.key).length }} 项)</span>
            <FontAwesomeIcon
              icon="chevron-down"
              :class="['mc-cat-toggle', isCollapsed('flat', cat.key) ? '' : 'expanded']"
              aria-hidden="true"
            />
          </button>

          <div v-if="!isCollapsed('flat', cat.key) && flatRows(cat.key).length" class="mc-category-table">
            <UiDataTable :data="flatRows(cat.key)" :columns="calcColumns" row-key="__rk">
              <template #column-body-supplier_name="{ row }">{{ (row as CalcRowVM).supplier_name || '-' }}</template>
              <template #column-body-material_name="{ row }">{{ (row as CalcRowVM).material_name }}</template>
              <template #column-body-specification="{ row }">{{ (row as CalcRowVM).specification || '-' }}</template>
              <template #column-body-total_quantity="{ row }">
                <span class="mc-qty-cell">{{ formatFillingQty(cat.key, row as CalcRowVM) }}</span>
              </template>
            </UiDataTable>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
// 物料用量计算结果列：分块卡渲染（默认 BOM 恒首）+ 扁平回退（A-5）。
// 缺陷②修复（A-9）：row-key 由不唯一的 material_name 改为复合键 `__rk`，
// 保证「同分类同名但规格/供应商/单位不同」的行全部渲染、不丢行。
import { reactive, computed } from 'vue'
import type { MaterialCalcRow, MaterialCalcScopeGroup } from '@/api'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
import { CALC_CATEGORY_LIST } from '@/composables/useMaterialCalculator'
import { scopeKeyOf, scopeNameOf } from '@/utils/roleMatrix'

const props = defineProps<{
  calcResults: Record<string, MaterialCalcRow[]>
  hasResults: boolean
  /** 按「产品 × 作用域」分块；缺失/空 → 回退扁平渲染（A-5）。 */
  calcGroups?: MaterialCalcScopeGroup[]
}>()

/** 带复合 row-key 的行视图模型。 */
type CalcRowVM = MaterialCalcRow & { __rk: string }

// 折叠状态：键 = `<scopeKey>::<category>`，不同作用域互不影响
const collapsed = reactive<Record<string, boolean>>({})
const categoryList = CALC_CATEGORY_LIST

const hasGroups = computed(() => (props.calcGroups?.length ?? 0) > 0)

/** 作用域唯一键（`p|<pid>|r|<rid|default>`）。 */
function groupKey(group: MaterialCalcScopeGroup): string {
  return scopeKeyOf(group)
}

/** 作用域展示名（默认 BOM → 默认BOM；角色名缺失 → 角色#<id>）。 */
function groupName(group: MaterialCalcScopeGroup): string {
  return scopeNameOf(group)
}

/** 读取某分类的行数组（安全索引，避免 undefined）。 */
function groupCat(group: MaterialCalcScopeGroup, category: string): MaterialCalcRow[] {
  const record = group as unknown as Record<string, MaterialCalcRow[] | undefined>
  const value = record[category]
  return Array.isArray(value) ? value : []
}

/**
 * 复合 row-key（A-9）：`<prefix>|<category>|<名称>|<规格>|<供应商>|<单位>`。
 * 同分类同名但规格/供应商/单位任一不同的行 → key 唯一 → 全部渲染。
 */
function rowKeyOf(prefix: string, category: string, row: MaterialCalcRow): string {
  return [
    prefix,
    category,
    row.material_name || row.name || '',
    row.specification || '',
    row.supplier_name || '',
    row.unit || '',
  ].join('|')
}

/** 给行附加 `__rk`（供 UiDataTable 作为 row-key 字段）。 */
function toVM(rows: MaterialCalcRow[] | undefined, prefix: string, category: string): CalcRowVM[] {
  return (rows ?? []).map((row) => ({ ...row, __rk: rowKeyOf(prefix, category, row) }))
}

function catRows(group: MaterialCalcScopeGroup, category: string): CalcRowVM[] {
  return toVM(groupCat(group, category), scopeKeyOf(group), category)
}

function flatRows(category: string): CalcRowVM[] {
  return toVM(props.calcResults?.[category], 'flat', category)
}

function toggle(scope: string, category: string) {
  const key = `${scope}::${category}`
  collapsed[key] = !collapsed[key]
}

function isCollapsed(scope: string, category: string): boolean {
  return !!collapsed[`${scope}::${category}`]
}

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

/* 作用域分块卡 */
.mc-scope-card {
  margin-bottom: 18px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 12px;
  padding: 10px 10px 4px;
  background: var(--color-surface-card, #fff);
}

.mc-scope-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 6px 10px;
}

.mc-scope-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 34px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  color: #fff;
}

.mc-scope-badge.is-default { background: var(--color-text-muted, #64748b); }
.mc-scope-badge.is-role { background: var(--color-primary-600, #2563eb); }

.mc-scope-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
}

.mc-scope-product {
  font-size: 12px;
  color: var(--color-text-secondary);
}

.mc-scope-qty {
  margin-left: auto;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-primary-700);
}

.mc-category-block {
  margin-bottom: 12px;
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
