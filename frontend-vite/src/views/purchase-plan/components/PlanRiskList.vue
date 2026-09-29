<template>
  <div class="sp-risk-list">
    <div v-if="!items.length" class="sp-risk-empty">本月暂无待处理风险</div>
    <template v-else>
      <button
        v-for="it in items"
        :key="it.date"
        class="sp-risk-row"
        @click="emit('select', it.date)"
      >
        <span class="sp-risk-info">
          <span class="sp-risk-date num">{{ short(it.date) }} · {{ fmt(it.qty) }}件</span>
          <span class="sp-risk-cust">{{ it.cust }}</span>
        </span>
        <span class="sp-risk-tag" :class="it.kind === 'overdue' ? 'sp-risk-r' : 'sp-risk-a'">{{ it.lbl }}</span>
      </button>
    </template>
  </div>
</template>

<script setup lang="ts">
// 风险清单 —— 从 PurchasePlanDailyTab 的内联标记抽出。
// 条目本身就是「跳到那天」的入口，故用 button 而非 div+click（可键盘触发、可被读屏识别）。
import type { RiskItem } from './types'

defineProps<{
  items: RiskItem[]
}>()

const emit = defineEmits<{
  select: [date: string]
}>()

/** 2026-09-08 → 09/08 */
function short(date: string): string {
  return date.slice(5).replace('-', '/')
}

function fmt(n: number): string {
  return Number(n || 0).toLocaleString('zh-CN')
}
</script>

<style scoped lang="scss">
.sp-risk-list {
  max-height: 420px;
  overflow-y: auto;
}

.sp-risk-empty {
  padding: 26px 16px;
  text-align: center;
  font-size: 13px;
  color: var(--color-text-muted, #8c96ad);
}

.sp-risk-row {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 16px;
  border: none;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 0;
  background: transparent;
  text-align: left;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.2s ease;
}

.sp-risk-row:last-child {
  border-bottom: none;
}

.sp-risk-row:hover {
  background: var(--color-primary-50);
}

.sp-risk-row:focus-visible {
  outline: 2px solid var(--color-primary-500);
  outline-offset: -2px;
}

.sp-risk-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.sp-risk-date {
  font-size: 13px;
  font-weight: 800;
  color: var(--color-heading);
}

.sp-risk-cust {
  font-size: 12px;
  color: var(--color-text-secondary, #5a6b8c);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sp-risk-tag {
  margin-left: auto;
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 6px;
  white-space: nowrap;
}

.sp-risk-r { background: var(--color-danger-100); color: var(--color-danger-700); }
.sp-risk-a { background: var(--color-warning-100); color: var(--color-warning-700); }
</style>
