<template>
  <div class="sp-toolbar">
    <div class="sp-toolbar-row">
      <div class="sp-toolbar-actions">
        <div class="sp-nav">
          <button class="sp-nav-btn" aria-label="上一页" @click="emit('prev-month')"><FontAwesomeIcon icon="chevron-left" aria-hidden="true" /></button>
          <span class="sp-nav-label">{{ y }}年{{ String(m).padStart(2, '0') }}月</span>
          <button class="sp-nav-btn" aria-label="下一页" @click="emit('next-month')"><FontAwesomeIcon icon="chevron-right" aria-hidden="true" /></button>
        </div>
        <UiSearchInput v-model="kw" :placeholder="viewTab === 'daily' ? '搜索日期、客户...' : '搜索产品、SKU、客户...'" @clear="kw = ''" />
        <button class="sp-action-btn" aria-label="导出" @click="emit('export')">导出</button>
        <button class="sp-action-btn sp-action-btn-primary" aria-label="新建" @click="emit('create')"><FontAwesomeIcon icon="plus" aria-hidden="true" />新建</button>
      </div>
      <div v-if="hasSummary" class="sp-toolbar-stats-wrapper">
        <div class="sp-toolbar-stats">
          <div class="sp-stat">
            <span class="sp-stat-label">总计划</span>
            <span class="sp-stat-value">{{ sKpi.allQty }}</span>
          </div>
          <div class="sp-stat">
            <span class="sp-stat-label">已出</span>
            <span class="sp-stat-value" :class="Number(sKpi.allShipped) > 0 ? 'sp-stat-success' : 'sp-stat-danger'">{{ sKpi.allShipped }}</span>
          </div>
          <div class="sp-stat">
            <span class="sp-stat-label">剩余</span>
            <span class="sp-stat-value sp-stat-warning">{{ sKpi.allRemain }}</span>
          </div>
        </div>
      </div>
    </div>
    <!-- KPI 阈值条（v5）：计划/已出/剩余/完成率/延期/临期 -->
    <div class="sp-kpi-strip">
      <div class="sp-kpi">
        <span class="sp-kpi-l">本月计划</span>
        <span class="sp-kpi-v num">{{ sKpi.allQty }}</span>
        <span class="sp-kpi-s num">{{ allQtyNum }}件</span>
      </div>
      <div class="sp-kpi">
        <span class="sp-kpi-l">本月已出</span>
        <span class="sp-kpi-v num" :class="allShippedNum > 0 ? '' : 'sp-kpi-v-r'">{{ sKpi.allShipped }}</span>
      </div>
      <div class="sp-kpi">
        <span class="sp-kpi-l">剩余</span>
        <span class="sp-kpi-v num sp-kpi-v-a">{{ sKpi.allRemain }}</span>
      </div>
      <div class="sp-kpi sp-kpi-rate">
        <span class="sp-kpi-l">完成率</span>
        <span class="sp-kpi-v num" :class="sKpi.pct <= 0 ? 'sp-kpi-v-r' : ''">{{ sKpi.pct }}%</span>
        <div class="sp-meter"><i :class="kpiMeterCls" :style="{ width: sKpi.pct + '%' }" /></div>
      </div>
      <div class="sp-kpi">
        <span class="sp-kpi-l" :class="risks.delayedCount > 0 ? 'sp-kpi-l-r' : ''">▲ 已延期</span>
        <span class="sp-kpi-v num" :class="risks.delayedCount > 0 ? 'sp-kpi-v-r' : ''">{{ risks.delayedCount }}</span>
        <span v-if="risks.delayedCount > 0" class="sp-kpi-s num">{{ risks.delayedQty }}件 · 最多{{ risks.maxDays }}天</span>
      </div>
      <div class="sp-kpi">
        <span class="sp-kpi-l" :class="risks.expiringCount > 0 ? 'sp-kpi-l-a' : ''">⧗ 临期≤3天</span>
        <span class="sp-kpi-v num" :class="risks.expiringCount > 0 ? 'sp-kpi-v-a' : ''">{{ risks.expiringCount }}</span>
        <span v-if="risks.expiringCount > 0" class="sp-kpi-s num">{{ risks.expiringQty }}件</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import UiSearchInput from '@/components/ui/UiSearchInput.vue'

interface SKpi {
  kpi0: string
  lbl0: string
  allQty: string
  allShipped: string
  allRemain: string
  pct: number
}

interface Risks {
  delayedCount: number
  delayedQty: number
  maxDays: number
  expiringCount: number
  expiringQty: number
}

const props = defineProps<{
  viewTab: 'daily' | 'summary'
  y: number
  m: number
  hasSummary: boolean
  sKpi: SKpi
  risks: Risks
}>()

const emit = defineEmits<{
  'update:globalKw': [v: string]
  'prev-month': []
  'next-month': []
  'export': []
  'create': []
}>()

const kw = defineModel<string>('globalKw', { default: '' })

const allShippedNum = computed(() => Number(props.sKpi.allShipped || 0))
const allQtyNum = computed(() => Number(props.sKpi.allQty || 0))
const kpiMeterCls = computed(() => {
  const p = props.sKpi.pct
  if (p <= 0) return 'sp-meter-r'
  if (p < 100) return 'sp-meter-a'
  return 'sp-meter-g'
})
</script>

<style scoped lang="scss">
.sp-toolbar {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px 24px 4px;
}

.sp-toolbar-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

/* KPI 阈值条 */
.sp-kpi-strip {
  display: flex;
  align-items: stretch;
  background: white;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 14px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  overflow: hidden;
}
.sp-kpi {
  flex: 1;
  min-width: 0;
  padding: 11px 16px;
  border-right: 1px solid var(--color-border-light, #e2e8f0);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.sp-kpi:last-child { border-right: none; }
.sp-kpi-rate { flex: 1.4; }
.sp-kpi-l {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text-muted, #5a6b8c);
  white-space: nowrap;
}
.sp-kpi-l-r { color: var(--color-danger-600); }
.sp-kpi-l-a { color: var(--color-warning-600); }
.sp-kpi-v {
  font-size: 22px;
  font-weight: 800;
  color: var(--color-heading);
  line-height: 1;
  margin-top: 3px;
}
.sp-kpi-v-r { color: var(--color-danger-600); }
.sp-kpi-v-a { color: var(--color-warning-600); }
.sp-kpi-s {
  font-size: 11px;
  color: var(--color-text-muted, #8c96ad);
  white-space: nowrap;
  margin-top: 3px;
  text-align: left;
}
.sp-meter {
  height: 6px;
  border-radius: 3px;
  background: #edf0f6;
  overflow: hidden;
  margin-top: 8px;
  max-width: 220px;
}
.sp-meter > i {
  display: block;
  height: 100%;
  border-radius: 3px;
}
.sp-meter-r { background: var(--color-danger-500, #e04042); }
.sp-meter-a { background: var(--color-warning-500, #f59e0b); }
.sp-meter-g { background: var(--color-success-500, #2a9a5b); }

.sp-toolbar-stats-wrapper {
  flex: 1;
  min-width: 0;
  display: flex;
  justify-content: flex-end;
}

.sp-toolbar-stats {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 14px;
  height: 45px;
  box-sizing: border-box;
  border-radius: var(--radius-input, 12px);
  border: 2px solid var(--color-border-light, #e2e8f0);
  background: transparent;
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
}

.sp-toolbar-stats:hover {
  border-color: var(--color-primary-300);
  box-shadow: 0 4px 12px rgba(0,0,0,0.06);
}

.sp-stat {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0;
}

.sp-stat + .sp-stat {
  padding-left: 12px;
  border-left: 1px solid var(--color-border-light, #e2e8f0);
}

.sp-stat-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text-muted);
  white-space: nowrap;
}

.sp-stat-value {
  font-size: 16px;
  font-weight: 800;
  color: var(--color-heading);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
}

.sp-stat-success {
  color: var(--color-success-600);
}

.sp-stat-success .sp-stat-value {
  color: var(--color-success-600);
}

.sp-stat-warning {
  color: var(--color-warning-600);
}

.sp-stat-warning .sp-stat-value {
  color: var(--color-warning-600);
}

.sp-stat-danger {
  color: var(--color-danger-600);
}

.sp-stat-danger .sp-stat-value {
  color: var(--color-danger-600);
}

.sp-toolbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.sp-nav {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.sp-nav-btn {
  width: 34px;
  height: 34px;
  border-radius: var(--radius-input, 12px);
  border: 1px solid var(--color-border-light, #e2e8f0);
  background: white;
  cursor: pointer;
  color: var(--color-text-secondary);
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: border-color 0.3s ease, color 0.3s ease, background 0.3s ease;
  flex-shrink: 0;
}

.sp-nav-btn:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-500);
  background: var(--color-primary-50);
}

.sp-nav-label {
  font-weight: 700;
  font-size: 14px;
  color: var(--color-heading);
  min-width: 90px;
  text-align: center;
  user-select: none;
}

.sp-action-btn {
  padding: 7px 14px;
  border-radius: 9px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  background: white;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  color: var(--color-primary-600);
  transition: background 0.3s ease, border-color 0.3s ease, transform 0.3s ease;
  font-family: inherit;
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.sp-action-btn:hover {
  background: var(--color-primary-50);
  border-color: var(--color-primary-300);
  transform: translateY(-1px);
}

.sp-action-btn-primary {
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700));
  border-color: transparent;
  color: white;
}

.sp-action-btn-primary:hover {
  background: linear-gradient(135deg, var(--color-primary-600), var(--color-primary-800));
  opacity: 0.95;
  box-shadow: 0 4px 12px rgba(91, 141, 239, 0.25);
}
</style>