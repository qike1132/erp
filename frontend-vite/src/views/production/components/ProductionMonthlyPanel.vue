<template>
  <div class="pr-main">
    <section class="pr-kpi-section">
      <div v-if="monthlySummary" class="pr-kpi-row">
        <KpiCard icon="cubes" color-class="pr-kpi-blue" label="月总产量" :value="monthlySummary.overall_quantity ?? 0" unit="件" />
        <KpiCard icon="yen-sign" color-class="pr-kpi-green" label="月总产值" :value="formatCurrency(monthlySummary.overall_value ?? 0)" />
        <KpiCard icon="calendar-check" color-class="pr-kpi-amber" label="生产天数" :value="monthlySummary.daily_data?.filter((d: any) => d.total.quantity > 0).length || 0" unit="天" />
      </div>
    </section>

    <section class="pr-dept-section">
      <div class="pr-section-label">部门概览</div>
      <div v-if="monthlySummary?.monthly_departments?.length" class="pr-dept-row">
        <div v-for="d in monthlySummary.monthly_departments" :key="d.department" :class="['pr-dept-card', `pr-dept-${d.department}`]">
          <div class="pr-dept-content">
            <div class="pr-dept-head">
              <div :class="['pr-dept-icon-sm', `pr-dept-icon-${d.department}`]"><i :class="deptIcon(d.department)" aria-hidden="true" /></div>
              <span class="pr-dept-name">{{ d.department_label }}</span>
            </div>
            <div class="pr-dept-qty">
              <span class="pr-dept-qty-num">{{ d.total_quantity }}</span>
              <span class="pr-dept-qty-unit">件</span>
            </div>
            <div class="pr-dept-stats">
              <div class="pr-dept-stat">
                <span class="pr-dept-stat-label">产值</span>
                <span class="pr-dept-stat-val">¥{{ formatMoney(d.total_value) }}</span>
              </div>
              <div class="pr-dept-stat">
                <span class="pr-dept-stat-label">SKU</span>
                <span class="pr-dept-stat-val">{{ d.sku_count }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="pr-content-section">
      <div class="pr-content-row">
        <div class="pr-chart-panel">
          <div class="pr-panel-header">
            <span class="pr-panel-title"><FontAwesomeIcon icon="chart-area" aria-hidden="true" /> 月度趋势</span>
          </div>
          <div :ref="setChartRef" class="pr-chart-body" />
        </div>
        <div v-if="monthlySummary?.daily_data?.length" class="pr-table-panel">
          <div class="pr-panel-header">
            <span class="pr-panel-title"><FontAwesomeIcon icon="table" aria-hidden="true" /> 每日明细</span>
          </div>
          <div class="pr-table-scroll">
            <UiDataTable
              :data="monthlySummary.daily_data"
              :columns="dailyDetailColumns"
              row-key="date"
            >
              <template #column-body-day="{ row }">
                <strong>{{ row.day }}日</strong>
              </template>
              <template #column-body-filling="{ row }">
                {{ row.filling?.quantity ?? 0 }}
              </template>
              <template #column-body-handcraft="{ row }">
                {{ row.handcraft?.quantity ?? 0 }}
              </template>
              <template #column-body-packaging="{ row }">
                {{ row.packaging?.quantity ?? 0 }}
              </template>
              <template #column-body-total="{ row }">
                <strong>{{ row.total?.quantity ?? 0 }}</strong>
              </template>
              <template #column-body-total_value="{ row }">
                ¥{{ formatMoney(row.total?.value ?? 0) }}
              </template>
            </UiDataTable>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import UiDataTable from '@/components/ui/UiDataTable.vue'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
import KpiCard from './KpiCard.vue'

defineProps<{
  // 月报 API 实际返回 overall_quantity / overall_value / daily_data / monthly_departments，
  // 与 @/types 的 MonthlySummary（monthly_total_quantity 等）字段名不一致；
  // 原主视图 useQuery 返回 any 直接访问，此处保持一致以避免类型回归。
  monthlySummary: any
  dailyDetailColumns: TableColumn[]
  formatCurrency: (v: number) => string
  formatMoney: (v: number) => string
  deptIcon: (d: string) => string
  setChartRef: (el: any) => void
}>()
</script>

<style scoped>
.pr-main { flex: 1; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 0; }
.pr-kpi-section { padding: 16px 24px 0; flex-shrink: 0; }
.pr-kpi-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.pr-kpi-card { display: flex; align-items: center; gap: 14px; padding: 18px 20px; border-radius: 12px; border: 1px solid #e2e8f0; background: white; transition: box-shadow 0.2s ease, border-color 0.2s ease; position: relative; overflow: hidden; }
.pr-kpi-card:hover { box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06); }
.pr-kpi-blue:hover { border-color: #bfdbfe; }
.pr-kpi-green:hover { border-color: #bbf7d0; }
.pr-kpi-amber:hover { border-color: #fde68a; }
.pr-kpi-icon-wrap { width: 48px; height: 48px; border-radius: 12px; display: flex; align-items: center; justify-content: center; font-size: 20px; flex-shrink: 0; }
.pr-kpi-blue .pr-kpi-icon-wrap { background: #eff6ff; color: #1e40af; }
.pr-kpi-green .pr-kpi-icon-wrap { background: #f0fdf4; color: #15803d; }
.pr-kpi-amber .pr-kpi-icon-wrap { background: #fffbeb; color: #d97706; }
.pr-kpi-body { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.pr-kpi-label { font-size: 12px; font-weight: 600; color: #64748b; letter-spacing: 0.03em; text-transform: uppercase; }
.pr-kpi-value { font-size: 24px; font-weight: 800; color: #1e293b; font-variant-numeric: tabular-nums; line-height: 1.2; }
.pr-kpi-unit { font-size: 13px; font-weight: 600; color: #64748b; margin-left: 3px; }

.pr-dept-section { padding: 12px 24px 0; flex-shrink: 0; }
.pr-section-label { font-size: 11px; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 8px; }
.pr-dept-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.pr-dept-card { display: flex; border-radius: 12px; border: 1px solid #e2e8f0; background: white; transition: border-color 0.2s ease, box-shadow 0.2s ease; }
.pr-dept-card:hover { box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04); }
.pr-dept-content { flex: 1; padding: 14px 16px; display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.pr-dept-head { display: flex; align-items: center; gap: 8px; }
.pr-dept-icon-sm { width: 28px; height: 28px; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 12px; }
.pr-dept-name { font-size: 13px; font-weight: 700; color: #1e293b; }
.pr-dept-qty { display: flex; align-items: baseline; gap: 4px; }
.pr-dept-qty-num { font-size: 26px; font-weight: 800; font-variant-numeric: tabular-nums; line-height: 1.1; }
.pr-dept-qty-unit { font-size: 13px; font-weight: 600; color: #64748b; }
.pr-dept-stats { display: flex; gap: 16px; }
.pr-dept-stat { display: flex; flex-direction: column; gap: 1px; }
.pr-dept-stat-label { font-size: 11px; font-weight: 500; color: #94a3b8; }
.pr-dept-stat-val { font-size: 12px; font-weight: 700; color: #475569; font-variant-numeric: tabular-nums; }
.pr-dept-filling .pr-dept-qty-num { color: #1e3a8a; }
.pr-dept-filling .pr-dept-icon-sm { background: #eff6ff; color: #1e40af; }
.pr-dept-filling:hover { border-color: #bfdbfe; }
.pr-dept-handcraft .pr-dept-qty-num { color: #14532d; }
.pr-dept-handcraft .pr-dept-icon-sm { background: #f0fdf4; color: #15803d; }
.pr-dept-handcraft:hover { border-color: #bbf7d0; }
.pr-dept-packaging .pr-dept-qty-num { color: #78350f; }
.pr-dept-packaging .pr-dept-icon-sm { background: #fffbeb; color: #d97706; }
.pr-dept-packaging:hover { border-color: #fde68a; }

.pr-content-section { padding: 12px 24px 16px; flex: 1; min-height: 0; }
.pr-content-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; height: 100%; min-height: 320px; }
.pr-chart-panel, .pr-table-panel { display: flex; flex-direction: column; min-height: 0; background: white; border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden; }
.pr-panel-header { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; border-bottom: 1px solid #f1f5f9; flex-shrink: 0; background: #fafbfc; }
.pr-panel-title { font-size: 13px; font-weight: 700; color: #1e293b; display: flex; align-items: center; gap: 6px; }
.pr-panel-title i { color: #3b82f6; font-size: 12px; }
.pr-chart-body { width: 100%; height: 280px; flex-shrink: 0; }
.pr-table-scroll { overflow-y: auto; overflow-x: auto; flex: 1; min-height: 0; }

@media (max-width: 1200px) {
  .pr-dept-row { grid-template-columns: repeat(3, 1fr); }
  .pr-content-row { grid-template-columns: 1fr; }
  .pr-chart-body { height: 240px; }
}
@media (max-width: 1024px) {
  .pr-kpi-section { padding: 12px 16px 0; }
  .pr-dept-section { padding: 10px 16px 0; }
  .pr-content-section { padding: 10px 16px 12px; }
  .pr-kpi-row { grid-template-columns: repeat(3, 1fr); gap: 8px; }
  .pr-kpi-card { padding: 14px 16px; }
  .pr-kpi-value { font-size: 20px; }
  .pr-dept-row { grid-template-columns: repeat(3, 1fr); gap: 8px; }
  .pr-dept-qty-num { font-size: 22px; }
}
@media (max-width: 768px) {
  .pr-kpi-section { padding: 8px 12px 0; }
  .pr-kpi-row { grid-template-columns: 1fr; gap: 8px; }
  .pr-kpi-card { padding: 12px 14px; }
  .pr-kpi-value { font-size: 20px; }
  .pr-kpi-icon-wrap { width: 40px; height: 40px; font-size: 16px; }
  .pr-dept-section { padding: 8px 12px 0; }
  .pr-dept-row { grid-template-columns: 1fr; gap: 8px; }
  .pr-content-section { padding: 8px 12px 12px; }
  .pr-content-row { grid-template-columns: 1fr; gap: 12px; min-height: auto; }
  .pr-chart-body { height: 220px; }
  .pr-panel-header { flex-wrap: wrap; gap: 6px; }
}
@media (min-width: 1440px) {
  .pr-kpi-value { font-size: 28px; }
  .pr-chart-body { height: 320px; }
}
</style>
