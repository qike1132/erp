<template>
  <div class="sp-fsum">
    <div class="sp-fsum-head"><span>按工厂汇总</span><span class="xs">计划量 · 已产 · 完成率</span></div>
    <div class="sp-fsum-grid">
      <div class="sp-fsum-cell" :data-tone="factoryTone(factory)">
        <span class="sp-fsum-name">{{ factory }}</span>
        <span class="sp-fsum-plan num">{{ fmt(row.plan) }}</span>
        <span class="sp-fsum-sub num">已产 {{ fmt(row.produced) }}</span>
        <div class="sp-fsum-meter"><i :class="pctCls(row.pct)" :style="{ width: row.pct + '%' }" /></div>
        <span class="sp-fsum-pct num">{{ row.pct }}%</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// 「月度汇总」Tab 顶部按工厂汇总卡片 —— 每个工厂 Tab 内展示当前工厂一行。
// customers 已由 useFactorySplit 按当前工厂收敛，其顶层 plan_qty/produced_qty 即该厂口径，
// 故此处直接对顶层求和，无需再拆 factories 桶。
import { computed } from 'vue'
import { factoryTone } from './factoryMeta'
import type { CustSumItem } from './types'

const props = defineProps<{ customers: CustSumItem[]; factory: string }>()
const row = computed(() => {
  let plan = 0, produced = 0
  for (const c of props.customers) { plan += Number(c.plan_qty || 0); produced += Number(c.produced_qty || 0) }
  return { plan, produced, pct: plan > 0 ? Math.floor(produced / plan * 1000) / 10 : 0 }
})
function fmt(n: number) { return Number(n || 0).toLocaleString('zh-CN') }
function pctCls(p: number) { return p <= 0 ? 'fm-r' : p < 100 ? 'fm-a' : 'fm-g' }
</script>

<style scoped lang="scss">
.sp-fsum {
  margin-bottom: 16px;
  background: white;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: var(--radius-md, 14px);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04), 0 4px 12px rgba(0, 0, 0, 0.06);
  overflow: hidden;
}

.sp-fsum-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 12px 18px;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
  font-size: 13px;
  font-weight: 800;
  color: var(--color-heading);
}

.sp-fsum-head .xs {
  font-size: 11px;
  font-weight: 500;
  color: var(--color-text-muted, #8c96ad);
}

.sp-fsum-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
  padding: 14px 18px;
}

.sp-fsum-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: var(--radius-sm, 10px);
  background: var(--color-bg-subtle, #fafbfd);
}

/* 工厂色档：东莞=主色蓝、湖北=紫、其余=中性 */
.sp-fsum-cell[data-tone='dg'] {
  border-left: 3px solid var(--color-primary-500, #5b8def);
}
.sp-fsum-cell[data-tone='hb'] {
  border-left: 3px solid var(--color-purple-500, #8b5cf6);
}
.sp-fsum-cell[data-tone='other'] {
  border-left: 3px solid var(--color-border, #cbd5e1);
}

.sp-fsum-name {
  font-size: 12px;
  font-weight: 700;
  color: var(--color-text-secondary, #5a6b8c);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sp-fsum-plan {
  font-size: 18px;
  font-weight: 800;
  color: var(--color-heading);
  line-height: 1.2;
}

.sp-fsum-sub {
  font-size: 11px;
  color: var(--color-text-muted, #8c96ad);
}

.sp-fsum-meter {
  height: 6px;
  border-radius: 3px;
  background: #edf0f6;
  overflow: hidden;
}

.sp-fsum-meter > i {
  display: block;
  height: 100%;
  border-radius: 3px;
}

.fm-r { background: var(--color-danger-500, #ef4444); }
.fm-a { background: var(--color-warning-500, #f59e0b); }
.fm-g { background: var(--color-success-500, #22c55e); }

.sp-fsum-pct {
  font-size: 12px;
  font-weight: 700;
  color: var(--color-text-secondary, #5a6b8c);
}

.num {
  font-variant-numeric: tabular-nums;
}
</style>
