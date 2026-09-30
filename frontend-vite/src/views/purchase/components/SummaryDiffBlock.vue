<template>
  <template v-if="diffs.length > 0">
    <!-- 差异横幅：说明「实际下单含手工调整」并点名不一致的物料（跨满 10 列） -->
    <tr class="sm-diff-banner">
      <td :colspan="10">
        ⚠ 本条「实际下单」含手工调整，与上方按 BOM 推算的明细不一致：
        <span v-for="(d, i) in diffs" :key="d.materialName">{{ i > 0 ? '、' : '' }}{{ d.materialName }}（推算 {{ formatQty(d.perSku) }} / 实际 {{ formatQty(d.stored) }}）</span>
      </td>
    </tr>
    <!--
      落库真值：该组全部物料（与采购单明细一致）。
      列序与主表后 5 格对齐：标签(客户/产品/订单数量/备品数量) | 供应商 | 布料名称 | 规格型号 | 损耗率 | 数量 | 单位。
      标签与供应商用 rowspan 跨行，故每行合计仍为 10 列（4 + 1 + 5）。
      率与数量由 composable 按主表同源口径算好，组件只做展示。
    -->
    <tr
      v-for="(r, i) in storedRows"
      :key="`diff-${i}`"
      class="sm-diff-row"
      :data-diff="isDiff(r) ? 'true' : undefined"
    >
      <td v-if="i === 0" :rowspan="storedRows.length" colspan="4" class="sm-diff-label">实际下单（含手工调整）</td>
      <td v-if="r.isSupplierFirst" :rowspan="r.supplierSpan">{{ r.supplierName }}</td>
      <td>{{ r.fabricName }}</td>
      <td>{{ r.specification }}</td>
      <td>{{ formatQty(r.rate) }}</td>
      <td class="sm-diff-qty">{{ r.displayQuantity }}</td>
      <td>{{ r.unit }}</td>
    </tr>
  </template>
</template>

<script setup lang="ts">
/**
 * SummaryDiffBlock.vue — 「数量差异对照块」（2026-09-30）。
 *
 * 按 SKU 展开的物料行是**算出来的**（BOM 单件用量 × 该 SKU 数量）；若某单用过
 * 「自定义编辑」手改过数量，各 SKU 之和会与库里存的合并真值对不上。此处把差异
 * **显式化**：横幅点名不一致的物料与两个数值，其下列出该组全部落库行并对不一致者描红。
 *
 * 数据行**与主表 10 列对齐**（标签跨 4 列 + 供应商 + 布料名称/规格型号/损耗率/数量/单位），
 * 且「损耗率」「数量」两格由 composable 按主表同源口径算好（快照率、加放后派生值），
 * 避免同一张表里两个「数量」口径不一致。本组件纯展示，无计算。
 *
 * 无差异时整块不渲染（`diffs` 为空 ⇒ 模板无输出），不占用表格高度。
 */
import { fmtQty as formatQty } from '@/utils/formatQty'
import type { DiffStoredRow } from '../composables/useFactoryTableRows'

const props = defineProps<{
  diffs: { materialName: string; perSku: number; stored: number }[]
  /** 该组落库真值（率/数量已按主表口径算好） */
  storedRows: DiffStoredRow[]
}>()

/** 该落库行是否属于「不一致」的物料（横幅点名的那些） */
function isDiff(row: DiffStoredRow): boolean {
  return props.diffs.some((d) => d.materialName === row.fabricName)
}
</script>

<style scoped lang="scss">
.sm-diff-banner > td {
  background: #fffaf0;
  color: #7a4a00;
  font-size: 12px;
  text-align: left;
}
.sm-diff-row > td {
  background: #fffaf0;
}
.sm-diff-label {
  font-weight: 700;
  color: #7a4a00;
}
.sm-diff-row[data-diff='true'] .sm-diff-qty {
  color: #c22;
  font-weight: 700;
}
</style>
