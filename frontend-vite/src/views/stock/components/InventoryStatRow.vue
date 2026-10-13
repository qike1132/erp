<template>
  <div class="sk-stat-row">
    <div
      v-for="s in stats"
      :key="s.label"
      class="sk-stat"
      :title="s.hint"
      :style="{ '--sk-stat-color': s.color, '--sk-stat-color-soft': s.colorSoft }"
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
 * 数字样式：本格强调色的渐变文字（`--sk-stat-color` 由模板按格下发）+ 入场浮起，
 * 见 <style> 的 `.sk-stat-value`；不支持 background-clip:text 的浏览器回落实色。
 */
import { computed } from 'vue'
import { formatNumber } from '@/utils/format'

const props = defineProps<{
  orders: number
  stockin: number
}>()

const stats = computed(() => [
  { label: '订单数量', hint: '未发完的订单数量', color: 'var(--color-primary-500)', colorSoft: 'var(--color-primary-300)', value: formatNumber(props.orders) },
  { label: '备货数量', hint: '已入库未消耗', color: 'var(--color-success-500)', colorSoft: 'var(--color-success-300)', value: formatNumber(props.stockin) },
  { label: '总订单', hint: '订单数量 + 备货数量', color: 'var(--color-info-500)', colorSoft: 'var(--color-info-200)', value: formatNumber(props.orders + props.stockin) },
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
  /* 回退色：不支持 background-clip:text 的浏览器（见下方 @supports）用实色，不会变透明 */
  color: var(--color-text);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
  /* 数据到达时浮起淡入一次（组件在拿到数据后才挂载，等于「加载完成」的入场） */
  animation: sk-stat-pop 0.45s cubic-bezier(0.22, 1, 0.36, 1) both;
}
/* 数字用本格强调色的渐变（深→浅），与左侧圆点同色系 */
@supports ((-webkit-background-clip: text) or (background-clip: text)) {
  .sk-stat-value {
    background-image: linear-gradient(
      92deg,
      var(--sk-stat-color, var(--color-primary-500)) 0%,
      var(--sk-stat-color-soft, var(--color-primary-300)) 100%
    );
    -webkit-background-clip: text;
    background-clip: text;
    /* 两写法都给：Blink/WebKit 认 -webkit-text-fill-color，Firefox 走 color */
    -webkit-text-fill-color: transparent;
    color: transparent;
  }
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
