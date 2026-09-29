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
            <th class="is-center">规格/色号</th>
            <th class="is-num">总采购量</th>
            <th>单位</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.__rk">
            <!-- .mc-table 是 table-layout:fixed + nowrap，长文本会被省略号截断
                 → 用 title 保证全文仍可悬浮查看（否则截断等于信息丢失） -->
            <td :title="row.supplier_name || ''">{{ row.supplier_name || '-' }}</td>
            <td :title="row.material_name || ''">
              {{ row.material_name }}<span v-if="showSkuCount && (row.sku_count ?? 0) > 1" class="mc-sku-badge">{{ row.sku_count }} 个SKU</span>
            </td>
            <td class="is-center" :title="row.specification || ''">{{ row.specification || '-' }}</td>
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

/** 带复合 row-key 的行视图模型（与 CalcResultColumn 的生成口径一致）。
 *  汇总视图下行带 `sku_count`（跨产品合并的 SKU 数，用于「N 个SKU」徽标）。 */
type CalcRowVM = MaterialCalcRow & { __rk: string; sku_count?: number }

withDefaults(
  defineProps<{
    /** 分类键：filling / fabric / accessory */
    categoryKey: string
    label: string
    icon: string
    rows: CalcRowVM[]
    collapsed: boolean
    /** 汇总视图：行带 sku_count > 1 时显示「N 个SKU」徽标（分块视图不显示）。 */
    showSkuCount?: boolean
  }>(),
  { showSkuCount: false },
)

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
   目标：让**相邻表头文字之间的空隙相等**。

   空隙公式（.mc-table 是 table-layout:fixed，padding 8px）：
       相邻空隙 = 本列盒宽 − 本列文字宽
   （左列的右内边距 + 右列的左内边距 = 16px，正好抵消，故 padding 不参与）
   ⇒ 要空隙处处相等，只需每列盒宽 = 文字宽 + 常数 C。
   实测表头文字宽 33 / 44 / 48.6 / 44 / 22（合计 191.6），表宽 394.7
   ⇒ 5C = 394.7 − 191.6 = 203.1 ⇒ C = 40.6
   ⇒ 目标盒宽 73.6 / 84.6 / 89.2 / 84.6 / 62.6 ⇒ 百分比 18.7 / 21.4 / 22.6 / 21.4 / 15.9

   「总采购量」列的表头与数据同带 .is-num 并居中、「规格/色号」列同带 .is-center 居中
   （见 app.css），数值不再贴右边界、与表头同轴。对齐方式不改变列盒宽，故上面的百分比仍然成立。

   百分比在 fixed 布局下是硬约束，表宽恒等于容器宽，不会溢出（见 app.css 的 .mc-table）。 */
.mc-col-supplier {
  width: 18.7%;
}
.mc-col-name {
  width: 21.4%;
}
.mc-col-spec {
  width: 22.6%;
}
.mc-col-qty {
  width: 21.4%;
}
.mc-col-unit {
  width: 15.9%;
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

/* 跨 SKU 合并徽标：物料名后的小胶囊（仅汇总视图 sku_count > 1 的行渲染） */
.mc-sku-badge {
  display: inline-block;
  margin-left: 4px;
  padding: 0 5px;
  border-radius: 999px;
  background: var(--color-primary-50, #eff5ff);
  color: var(--color-primary-700);
  font-size: 9.5px;
  font-weight: 700;
  line-height: 15px;
  vertical-align: 1px;
}
</style>
