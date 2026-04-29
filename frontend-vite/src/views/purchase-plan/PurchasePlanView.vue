<template>
  <div class="pp-page">
    <div class="pp-header">
      <div class="pp-header-left">
        <h2 class="pp-title">出货计划</h2>
        <p class="pp-desc">管理出货排期，追踪出货进度，对比库存状况</p>
      </div>
      <div class="pp-header-right">
        <div class="pp-month-nav">
          <button class="pp-nav-btn" @click="prevMonth"><i class="fas fa-chevron-left" /></button>
          <span class="pp-month-label">{{ currentYear }}年{{ currentMonth }}月</span>
          <button class="pp-nav-btn" @click="nextMonth"><i class="fas fa-chevron-right" /></button>
          <button class="pp-today-btn" @click="goToday">本月</button>
        </div>
        <div class="pp-view-switch">
          <button
            v-for="v in views"
            :key="v.key"
            class="pp-vs-btn"
            :class="{ active: activeView === v.key }"
            @click="activeView = v.key"
          >
            <i :class="v.icon" /> {{ v.label }}
          </button>
        </div>
      </div>
    </div>

    <div class="pp-kpi-bar">
      <div class="pp-kpi" :class="`pp-kpi-${k.color}`" v-for="k in kpis" :key="k.key">
        <div class="pp-kpi-icon"><i :class="k.icon" /></div>
        <div class="pp-kpi-body">
          <span class="pp-kpi-val">{{ k.value }}</span>
          <span class="pp-kpi-lbl">{{ k.label }}</span>
        </div>
      </div>
    </div>

    <div class="pp-filter-bar">
      <div class="pp-filters">
        <UiSelect
          v-model="filters.customer_id"
          placeholder="全部客户"
          :options="customerOptions"
          style="width: 180px"
        />
        <UiSelect
          v-model="filters.status"
          placeholder="全部状态"
          :options="statusOptions"
          style="width: 140px"
        />
      </div>
      <div class="pp-actions">
        <UiButton size="sm" variant="primary" @click="showCreateDialog = true">
          <i class="fas fa-plus" style="margin-right: 4px" />新增计划
        </UiButton>
        <UiButton size="sm" variant="success" @click="showBatchDialog = true">
          <i class="fas fa-file-upload" style="margin-right: 4px" />批量导入
        </UiButton>
      </div>
    </div>

    <div class="pp-content">
      <PlanCalendarTab
        v-if="activeView === 'calendar'"
        :year="currentYear"
        :month="currentMonth"
        :customer-id="filters.customer_id"
        @select-date="handleSelectDate"
        @view-plan="handleViewPlan"
      />
      <PlanListTab
        v-if="activeView === 'schedule'"
        :year="currentYear"
        :month="currentMonth"
        :customer-id="filters.customer_id"
        :status="filters.status"
        @view-plan="handleViewPlan"
        @edit-plan="handleEditPlan"
      />
      <PlanStatsTab
        v-if="activeView === 'stats'"
        :year="currentYear"
        :month="currentMonth"
      />
      <PlanInventoryTab
        v-if="activeView === 'inventory'"
        :year="currentYear"
        :month="currentMonth"
        :customer-id="filters.customer_id"
      />
    </div>

    <CreatePlanDialog v-model:open="showCreateDialog" />
    <BatchUploadDialog v-model:open="showBatchDialog" />
    <PlanDetailDrawer
      v-model:open="showDetailDrawer"
      :plan-id="selectedPlanId"
      @edited="handlePlanEdited"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { planApi, customerApi } from '@/api'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiButton from '@/components/ui/UiButton.vue'
import PlanCalendarTab from './components/PlanCalendarTab.vue'
import PlanListTab from './components/PlanListTab.vue'
import PlanStatsTab from './components/PlanStatsTab.vue'
import PlanInventoryTab from './components/PlanInventoryTab.vue'
import CreatePlanDialog from './components/CreatePlanDialog.vue'
import BatchUploadDialog from './components/BatchUploadDialog.vue'
import PlanDetailDrawer from './components/PlanDetailDrawer.vue'

const views = [
  { key: 'calendar', label: '日历', icon: 'fas fa-calendar-alt' },
  { key: 'schedule', label: '排程', icon: 'fas fa-table-list' },
  { key: 'stats', label: '统计', icon: 'fas fa-chart-bar' },
  { key: 'inventory', label: '库存', icon: 'fas fa-warehouse' },
]

const activeView = ref('calendar')
const showCreateDialog = ref(false)
const showBatchDialog = ref(false)
const showDetailDrawer = ref(false)
const selectedPlanId = ref(0)

const now = new Date()
const currentYear = ref(now.getFullYear())
const currentMonth = ref(now.getMonth() + 1)

const filters = reactive({ customer_id: '', status: '' })

const statusOptions = [
  { value: '', label: '全部状态' },
  { value: 'pending', label: '待确认' },
  { value: 'confirmed', label: '已确认' },
  { value: 'completed', label: '已完成' },
  { value: 'cancelled', label: '已取消' },
]

const { data: namesData } = useQuery({
  queryKey: ['customer-active-names'],
  queryFn: async () => { const r = (await customerApi.activeNames()) as any; return r.names ?? r ?? [] },
  staleTime: 60_000,
})

const customerOptions = computed(() => {
  const arr = Array.isArray(namesData.value) ? namesData.value : []
  return [{ value: '', label: '全部客户' }, ...arr.map((c: any) => ({ value: String(c.id ?? ''), label: c.name ?? c }))]
})

const { data: monthlyData } = useQuery({
  queryKey: ['plan-monthly-overview', () => currentYear.value, () => currentMonth.value, () => filters.customer_id],
  queryFn: async () => {
    const p: any = { year: currentYear.value, month: currentMonth.value }
    if (filters.customer_id) p.customer_id = Number(filters.customer_id)
    return (await planApi.monthly(p)) as any
  },
  staleTime: 30_000,
})

const kpis = computed(() => {
  const pbd = monthlyData.value?.plans_by_date ?? {}
  let totalPlan = 0, totalShipped = 0, totalRemaining = 0, dateCount = 0
  for (const [, items] of Object.entries(pbd)) {
    const arr = items as any[]
    if (!arr?.length) continue
    dateCount++
    for (const i of arr) {
      totalPlan += Number(i.quantity || 0)
      totalShipped += Number(i.shipped_qty || 0)
      totalRemaining += Number(i.remaining_qty || 0)
    }
  }
  const rate = totalPlan > 0 ? Math.round((totalShipped / totalPlan) * 100) : 0
  return [
    { key: 'days', label: '出货日', value: dateCount, icon: 'fas fa-calendar-check', color: 'blue' },
    { key: 'total', label: '计划总量', value: totalPlan, icon: 'fas fa-boxes-stacked', color: 'ocean' },
    { key: 'shipped', label: '已出货', value: `${totalShipped} (${rate}%)`, icon: 'fas fa-truck', color: 'green' },
    { key: 'remaining', label: '待出货', value: totalRemaining, icon: 'fas fa-hourglass-half', color: 'orange' },
  ]
})

function prevMonth() {
  if (currentMonth.value === 1) { currentMonth.value = 12; currentYear.value-- }
  else currentMonth.value--
}
function nextMonth() {
  if (currentMonth.value === 12) { currentMonth.value = 1; currentYear.value++ }
  else currentMonth.value++
}
function goToday() {
  const t = new Date()
  currentYear.value = t.getFullYear()
  currentMonth.value = t.getMonth() + 1
}

function handleSelectDate(date: string) {
  activeView.value = 'schedule'
}
function handleViewPlan(planId: number) {
  selectedPlanId.value = planId
  showDetailDrawer.value = true
}
function handleEditPlan(planId: number) {
  selectedPlanId.value = planId
  showDetailDrawer.value = true
}
function handlePlanEdited() {
}
</script>

<style scoped>
.pp-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.pp-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  flex-wrap: wrap;
}
.pp-title {
  font-size: 1.5rem;
  font-weight: 800;
  color: var(--color-heading);
  margin: 0;
  line-height: 1.2;
}
.pp-desc {
  font-size: 0.82rem;
  color: var(--color-text-secondary);
  margin: 4px 0 0;
}
.pp-header-right {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.pp-month-nav {
  display: flex;
  align-items: center;
  gap: 6px;
}
.pp-nav-btn {
  width: 32px; height: 32px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--color-border-light);
  background: var(--color-surface-card);
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  color: var(--color-text-secondary);
  font-size: 0.72rem;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
.pp-nav-btn:hover {
  border-color: var(--color-primary-500);
  color: var(--color-primary-500);
  background: var(--color-primary-50);
  box-shadow: 0 2px 8px rgba(91, 141, 239, 0.15);
}
.pp-month-label {
  font-size: 0.95rem;
  font-weight: 700;
  color: var(--color-text);
  min-width: 100px;
  text-align: center;
}
.pp-today-btn {
  padding: 5px 12px;
  border-radius: 8px;
  border: 1px solid var(--color-primary-200);
  background: var(--color-primary-50);
  cursor: pointer;
  color: var(--color-primary-500);
  font-size: 0.75rem;
  font-weight: 600;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
.pp-today-btn:hover {
  background: var(--color-primary-100);
  border-color: var(--color-primary-500);
  box-shadow: 0 2px 8px rgba(91, 141, 239, 0.15);
}

.pp-view-switch {
  display: flex;
  background: var(--color-surface-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-button);
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}
.pp-vs-btn {
  padding: 7px 14px;
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--color-text-secondary);
  transition: all 0.3s;
  display: flex;
  align-items: center;
  gap: 4px;
}
.pp-vs-btn i { font-size: 0.72rem; }
.pp-vs-btn:hover { color: var(--color-primary-500); }
.pp-vs-btn.active {
  background: var(--gradient-primary);
  color: white;
  box-shadow: 0 2px 8px rgba(91, 141, 239, 0.3);
}

.pp-kpi-bar {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.pp-kpi {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  background: var(--color-surface-card);
  border-radius: var(--radius-card);
  border: 1px solid var(--color-border-light);
  box-shadow: var(--shadow-sm);
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}
.pp-kpi:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}
.pp-kpi-icon {
  width: 42px; height: 42px;
  border-radius: var(--radius-md);
  display: flex; align-items: center; justify-content: center;
  font-size: 1rem;
}
.pp-kpi-body { display: flex; flex-direction: column; gap: 2px; }
.pp-kpi-val { font-size: 1.35rem; font-weight: 900; line-height: 1; }
.pp-kpi-lbl { font-size: 0.7rem; font-weight: 600; color: var(--color-text-secondary); }

.pp-kpi-blue .pp-kpi-icon { background: var(--color-primary-50); color: var(--color-primary-500); }
.pp-kpi-blue .pp-kpi-val { color: var(--color-primary-500); }
.pp-kpi-ocean .pp-kpi-icon { background: var(--color-ocean-light); color: var(--color-ocean-text); }
.pp-kpi-ocean .pp-kpi-val { color: var(--color-heading); }
.pp-kpi-green .pp-kpi-icon { background: var(--color-success-50); color: var(--color-success-500); }
.pp-kpi-green .pp-kpi-val { color: var(--color-success-500); }
.pp-kpi-orange .pp-kpi-icon { background: var(--color-warning-50); color: var(--color-warning-500); }
.pp-kpi-orange .pp-kpi-val { color: var(--color-warning-500); }

.pp-filter-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.pp-filters {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.pp-actions {
  display: flex;
  gap: 8px;
}

@media (max-width: 1024px) {
  .pp-kpi-bar { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 640px) {
  .pp-header { flex-direction: column; }
  .pp-header-right { align-self: flex-end; flex-wrap: wrap; }
  .pp-kpi-bar { grid-template-columns: 1fr 1fr; }
  .pp-filter-bar { flex-direction: column; align-items: stretch; }
  .pp-actions { justify-content: flex-end; }
}
</style>
