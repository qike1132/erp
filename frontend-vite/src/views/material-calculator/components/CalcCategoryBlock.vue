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
        <colgroup>
          <col class="mc-col-supplier" />
          <col class="mc-col-name" />
          <col class="mc-col-spec" />
          <col class="mc-col-qty" />
          <col class="mc-col-unit" />
        </colgroup>
        <thead>
          <tr>
            <th>供应商</th>
            <th>物料名称</th>
            <th>规格/色号</th>
            <th class="is-num">总采购量</th>
            <th>单位</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.__rk">
            <td>{{ row.supplier_name || '-' }}</td>
            <td>{{ row.material_name }}</td>
            <td>{{ row.specification || '-' }}</td>
            <td class="is-num">{{ quantityOf(categoryKey, row) }}</td>
            <td>{{ unitOf(categoryKey, row) }}</td>
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

// 填充类总采购量按克自动换算为 kg：克/g → kg，其他单位原样显示。
// 「数量」与「单位」各自成列（单位独立成列后，换算后的单位必须跟着变，不能各说各话）。

/** 填充类且单位为克/g → 换算系数 1000（其余一律 1）。 */
function gramScale(catKey: string, row: CalcRowVM): number {
  if (catKey !== 'filling') return 1
  const unit = (row.unit || '').trim()
  return unit === '克' || unit.toLowerCase() === 'g' ? 1000 : 1
}

/** 总采购量数值列：换算后最多保留 3 位小数，去掉尾随零。 */
function quantityOf(catKey: string, row: CalcRowVM): string {
  const scale = gramScale(catKey, row)
  if (scale === 1) return `${row.total_quantity}`
  return `${parseFloat((row.total_quantity / scale).toFixed(3))}`
}

/** 单位列：克 → kg；其余原样（空单位回落 '-'，与其它文本列一致）。 */
function unitOf(catKey: string, row: CalcRowVM): string {
  if (gramScale(catKey, row) === 1000) return 'kg'
  return (row.unit || '').trim() || '-'
}
</script>

<style scoped>
/* 列宽配比（colgroup 上的百分比）。
   背景：auto 布局按「内容宽比例」分配多余空间，实测 1600px 视口下空白占全表 47.4%，
   其中「物料名称」一列独占 63.8px（是其文字宽的 1.4 倍），而「总采购量」表头
   本身就有 60px 文字、只分到 80px 列宽，视觉上数字被挤到贴边、名称后却空一大截。
   这里按「表头文字宽 + 典型内容宽」给出目标配比，仍保留 auto 布局：
   百分比是**目标值**而非硬约束，窄列下浏览器仍会保证内容不溢出（不换行、不截断）。 */
.mc-col-supplier {
  width: 20%;
}
.mc-col-name {
  width: 24%;
}
.mc-col-spec {
  width: 25%;
}
.mc-col-qty {
  width: 19%;
}
.mc-col-unit {
  width: 12%;
}

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
