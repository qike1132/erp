<template>
  <div class="sp-toolbar">
    <div class="sp-toolbar-actions">
      <div class="sp-nav">
        <button class="sp-nav-btn" @click="emit('prev-month')" aria-label="上一页"><FontAwesomeIcon icon="chevron-left" aria-hidden="true" /></button>
        <span class="sp-nav-label">{{ y }}年{{ String(m).padStart(2, '0') }}月</span>
        <button class="sp-nav-btn" @click="emit('next-month')" aria-label="下一页"><FontAwesomeIcon icon="chevron-right" aria-hidden="true" /></button>
      </div>
      <UiSearchInput v-model="kw" :placeholder="viewTab === 'daily' ? '搜索日期、客户...' : '搜索产品、SKU、客户...'" @clear="kw = ''" />
      <button class="sp-action-btn" @click="emit('export')" aria-label="导出">导出</button>
      <button class="sp-action-btn sp-action-btn-primary" @click="emit('create')" aria-label="新建"><FontAwesomeIcon icon="plus" aria-hidden="true" />新建</button>
    </div>
    <div v-if="hasSummary" class="sp-toolbar-stats-wrapper">
      <div class="sp-toolbar-stats">
        <div class="sp-stat">
          <span class="sp-stat-label">总计划</span>
          <span class="sp-stat-value">{{ sKpi.allQty }}</span>
        </div>
        <div class="sp-stat">
          <span class="sp-stat-label">已出</span>
          <span class="sp-stat-value sp-stat-success">{{ sKpi.allShipped }}</span>
        </div>
        <div class="sp-stat">
          <span class="sp-stat-label">剩余</span>
          <span class="sp-stat-value sp-stat-warning">{{ sKpi.allRemain }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import UiSearchInput from '@/components/ui/UiSearchInput.vue'

interface SKpi {
  kpi0: string
  lbl0: string
  allQty: string
  allShipped: string
  allRemain: string
  pct: number
}

const props = defineProps<{
  viewTab: 'daily' | 'summary'
  y: number
  m: number
  hasSummary: boolean
  sKpi: SKpi
}>()

const emit = defineEmits<{
  'update:globalKw': [v: string]
  'prev-month': []
  'next-month': []
  'export': []
  'create': []
}>()

const kw = defineModel<string>('globalKw', { default: '' })
</script>

<style scoped lang="scss">
.sp-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 24px;
  flex-wrap: wrap;
}

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