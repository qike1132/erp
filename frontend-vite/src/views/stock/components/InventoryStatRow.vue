<template>
  <div class="sk-stat-row">
    <div
      v-for="s in stats"
      :key="s.label"
      class="sk-stat"
      :title="s.hint"
    >
      <div class="sk-stat-top">
        <span class="sk-stat-dot" :style="{ background: s.color }" aria-hidden="true" />
        <span class="sk-stat-label">{{ s.label }}</span>
      </div>
      <div class="sk-stat-value">{{ s.value }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * InventoryStatRow.vue — 库存页头部的三格汇总（紧凑两行式）
 *
 * 只保留与表格列同名的三项：订单数量 / 备货数量 / 总订单。
 * 原「可用库存」格已删（改由表格列承载时会有语义重复）；
 * 口径说明放在 title 提示里，避免占行内空间（整行工具条要放搜索与导出）。
 *
 * 数字样式（2026-10-14）：三项数字统一走常规文本色，不再按格下发强调色，
 * 也没有渐变文字（原 background-clip:text 渐变已移除）；唯一保留的颜色是标签前的
 * 小圆点（`s.color`，纯装饰的分组标记）。
 */
import { computed } from 'vue'
import { formatNumber } from '@/utils/format'

const props = defineProps<{
  orders: number
  stockin: number
}>()

const stats = computed(() => [
  { label: '订单数量', hint: '未发完的订单数量', color: 'var(--color-primary-500)', value: formatNumber(props.orders) },
  { label: '备货数量', hint: '已入库未消耗', color: 'var(--color-success-500)', value: formatNumber(props.stockin) },
  { label: '总订单', hint: '订单数量 + 备货数量', color: 'var(--color-info-500)', value: formatNumber(props.orders + props.stockin) },
])
</script>

<style scoped>
.sk-stat-row {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}
.sk-stat {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 0 16px;
  cursor: default;
}
.sk-stat + .sk-stat {
  border-left: 1px solid var(--color-border-light, #f0f2f5);
}
.sk-stat-top {
  display: flex;
  align-items: center;
  gap: 5px;
}
.sk-stat-dot {
  width: 6px;
  height: 6px;
  border-radius: 2px;
  flex-shrink: 0;
}
.sk-stat-label {
  font-size: 11px;
  font-weight: 500;
  color: var(--color-text-secondary);
  white-space: nowrap;
}
.sk-stat-value {
  font-size: 17px;
  font-weight: 700;
  line-height: 1.2;
  /* 常规文本色：三项完全一致（2026-10-14 起不再有渐变/彩色字/透明填充） */
  color: var(--color-text);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
  /* 数据到达时浮起淡入一次（组件在拿到数据后才挂载，等于「加载完成」的入场） */
  animation: sk-stat-pop 0.45s cubic-bezier(0.22, 1, 0.36, 1) both;
}
@keyframes sk-stat-pop {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: none; }
}
@media (prefers-reduced-motion: reduce) {
  .sk-stat-value { animation: none; }
}
@media (max-width: 980px) {
  .sk-stat-row { flex: 1; }
  .sk-stat { flex: 1; padding: 0 10px; align-items: flex-start; }
  .sk-stat + .sk-stat { border-left: none; }
}
</style>
