<template>
  <div class="mc-category-block" :class="'mc-cat-' + categoryKey">
    <button
      class="mc-category-header"
      :aria-label="`${label}（${rows.length} 项）`"
      @click="emit('toggle')"
    >
      <FontAwesomeIcon :icon="icon" class="mc-cat-icon" aria-hidden="true" />
      <span class="mc-cat-label">{{ label }}</span>
      <span class="mc-cat-count">{{ rows.length }}</span>
      <FontAwesomeIcon
        icon="chevron-down"
        :class="['mc-cat-toggle', collapsed ? '' : 'expanded']"
        aria-hidden="true"
      />
    </button>

    <div v-if="!collapsed" class="mc-category-table">
      <table class="mc-table">
        <thead>
          <tr>
            <th>供应商</th>
            <th>物料名称</th>
            <th>规格</th>
            <th class="is-num">总采购量</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.__rk">
            <td>{{ row.supplier_name || '-' }}</td>
            <td>{{ row.material_name }}</td>
            <td>{{ row.specification || '-' }}</td>
            <td class="is-num">{{ formatQuantity(categoryKey, row) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 单个物料分类区块（32px 折叠头 + 紧凑结果表）。
 * 从 CalcResultColumn.vue 抽出：分类头样式、分类色变量与单位换算自成一体的内聚单元，
 * 同时把单个 SFC 控制在质量门禁阈值（400 行）以内。
 */
import type { MaterialCalcRow } from '@/api'

/** 带复合 row-key 的行视图模型（与 CalcResultColumn 的生成口径一致）。 */
type CalcRowVM = MaterialCalcRow & { __rk: string }

defineProps<{
  /** 分类键：filling / fabric / accessory */
  categoryKey: string
  label: string
  icon: string
  rows: CalcRowVM[]
  collapsed: boolean
}>()

const emit = defineEmits<{
  toggle: []
}>()

// 填充类总采购量按克自动换算为 kg：克/g → kg，其他单位原样显示
function formatQuantity(catKey: string, row: CalcRowVM): string {
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
</script>

<style scoped>
/* 区块之间 1px 分隔线，末尾不加 */
.mc-category-block {
  border-bottom: var(--bw) solid var(--color-border-light);
}
.mc-category-block:last-child {
  border-bottom: 0;
}

/* 分类色：以 CSS 变量下发给图标。
   原先分类头用 linear-gradient 背景 + 46px 高度，是结果列密度问题的主因之一。 */
.mc-cat-filling {
  --mc-cat: var(--color-primary-700);
}
.mc-cat-fabric {
  --mc-cat: var(--color-success-700);
}
.mc-cat-accessory {
  --mc-cat: var(--color-warning-800);
}

.mc-category-header {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  width: 100%;
  height: 32px;
  padding: 0 var(--sp-1);
  border: 0;
  border-radius: var(--r-xs);
  background: transparent;
  text-align: left;
  cursor: pointer;
  color: var(--color-text);
  transition: background 0.15s ease;
}
.mc-category-header:hover {
  background: var(--color-slate-50);
}

/* FontAwesomeIcon 渲染的是 <svg>，尺寸/颜色必须打在 svg 上 */
.mc-cat-icon {
  width: 12px;
  height: 12px;
  flex-shrink: 0;
  color: var(--mc-cat, var(--color-text-muted));
}

.mc-cat-label {
  font-size: var(--fs-xs);
  font-weight: 600;
}

.mc-cat-count {
  font-size: var(--fs-cap);
  color: var(--color-text-muted);
  font-variant-numeric: tabular-nums;
}

.mc-cat-toggle {
  margin-left: auto;
  width: 11px;
  height: 11px;
  color: var(--color-text-muted);
  transition: transform 0.2s ease;
}
.mc-cat-toggle.expanded {
  transform: rotate(180deg);
}

.mc-category-table {
  padding-bottom: var(--sp-2);
}
</style>
