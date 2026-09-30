<template>
  <template v-if="diffs.length > 0">
    <!-- 差异横幅：说明「实际下单含手工调整」并点名不一致的物料 -->
    <tr class="sm-diff-banner">
      <td :colspan="10">
        ⚠ 本条「实际下单」含手工调整，与上方按 BOM 推算的明细不一致：
        <span v-for="(d, i) in diffs" :key="d.materialName">{{ i > 0 ? '、' : '' }}{{ d.materialName }}（推算 {{ formatQty(d.perSku) }} / 实际 {{ formatQty(d.stored) }}）</span>
      </td>
    </tr>
    <!-- 落库真值：该组全部物料（与采购单明细一致） -->
    <tr
      v-for="(f, i) in storedFabrics"
      :key="`diff-${i}`"
      class="sm-diff-row"
      :data-diff="isDiff(f) ? 'true' : 'false'"
    >
      <td v-if="i === 0" :rowspan="storedFabrics.length" class="sm-diff-label">实际下单（含手工调整）</td>
      <td>{{ f.fabric_name }}</td>
      <td>{{ f.specification || '' }}</td>
      <td>{{ f.unit || '' }}</td>
      <td class="sm-diff-qty">{{ formatQty(f.quantity) }}</td>
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
 * 无差异时整块不渲染（`diffs` 为空 ⇒ 模板无输出），不占用表格高度。
 */
import { fmtQty as formatQty } from '@/utils/formatQty'
import type { FabricItem } from '../composables/useSummaryModal'

const props = defineProps<{
  diffs: { materialName: string; perSku: number; stored: number }[]
  /** 该组落库真值（既有 suppliers[].fabrics 汇总而来） */
  storedFabrics: FabricItem[]
}>()

/** 该落库行是否属于「不一致」的物料（横幅点名的那些） */
function isDiff(fabric: FabricItem): boolean {
  return props.diffs.some((d) => d.materialName === fabric.fabric_name)
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
