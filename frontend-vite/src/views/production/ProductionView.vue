<template>
  <div class="pr-container">
    <div class="page-card page-card-main">

      <ProductionToolbar
        v-model:view-tab="viewTab"
        v-model:date-ref="dateRef"
        :monthly-year="monthlyYear"
        :monthly-month="monthlyMonth"
        @prev-day="goPrevDay"
        @next-day="goNextDay"
        @prev-month="prevMonth"
        @next-month="nextMonth"
        @today="goToday"
        @open-entry="showEntryDrawer = true"
        @export="handleExport"
      />

      <!-- ============ 日报 TAB ============ -->
      <ProductionDailyPanel
        v-show="viewTab === 'daily'"
        :report-summary="reportSummary"
        :dept-summary-columns="deptSummaryColumns"
        :report-date="reportDate"
        :format-currency="formatCurrency"
        :format-money="formatMoney"
        :dept-icon="deptIcon"
        :set-chart-ref="setDailyChartRef"
      />

      <!-- ============ 月报 TAB ============ -->
      <ProductionMonthlyPanel
        v-show="viewTab === 'monthly'"
        :monthly-summary="monthlySummary"
        :daily-detail-columns="dailyDetailColumns"
        :format-currency="formatCurrency"
        :format-money="formatMoney"
        :dept-icon="deptIcon"
        :set-chart-ref="setMonthlyChartRef"
      />

      <!-- ============ 录入弹窗 ============ -->
      <ProductionEntryDrawer
        ref="entryDrawerRef"
        v-model:open="showEntryDrawer"
        v-model:selected-date="selectedDate"
      />

      <!-- ============ 导出进度提示 ============ -->
      <Transition name="pr-toast">
        <div v-if="exportStatus.show" :class="['pr-export-toast', exportStatus.type]">
          <i :class="exportStatus.icon" aria-hidden="true" />
          <span>{{ exportStatus.message }}</span>
        </div>
      </Transition>
    </div>
  </div>
  <UiConfirmDialog
    :open="confirmDialog.open"
    :text="confirmDialog.text"
    :sub="confirmDialog.sub"
    :type="confirmDialog.type"
    @confirm="confirmDialog.onConfirm"
    @cancel="confirmDialog.onCancel"
  />
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { dailyProductionApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
import { formatCurrency, formatNumber } from '@/utils/format'
import { useProductionCharts } from './composables/useProductionCharts'

import ProductionToolbar from './components/ProductionToolbar.vue'
import ProductionDailyPanel from './components/ProductionDailyPanel.vue'
import ProductionMonthlyPanel from './components/ProductionMonthlyPanel.vue'
import ProductionEntryDrawer from './components/ProductionEntryDrawer.vue'

const _timers: ReturnType<typeof setTimeout>[] = []
const confirmDialog = useConfirmDialog()
const formatMoney = formatNumber

const departments = [
  { value: 'filling', label: '充棉部', icon: 'fas fa-cloud' },
  { value: 'handcraft', label: '手工部', icon: 'fas fa-hand-sparkles' },
  { value: 'packaging', label: '包装部', icon: 'fas fa-box' },
]
function deptIcon(d: string) { return departments.find(x => x.value === d)?.icon ?? 'fas fa-building' }

// ===== 核心状态 =====
const viewTab = ref('daily')
const selectedDate = ref(todayLocal())
const reportDate = ref(todayLocal())
const showEntryDrawer = ref(false)
const monthlyYear = ref(new Date().getFullYear())
const monthlyMonth = ref(new Date().getMonth() + 1)

const dateRef = computed({
  get: () => viewTab.value === 'daily' ? reportDate.value : selectedDate.value,
  set: (v: string) => { if (viewTab.value === 'daily') reportDate.value = v; else selectedDate.value = v },
})

// ===== 数据查询 =====
const { data: reportSummaryData } = useQuery({
  queryKey: ['daily-production-daily-summary', reportDate],
  queryFn: () => dailyProductionApi.dailySummary(reportDate.value) as Promise<any>,
  staleTime: 30_000,
})
const reportSummary = computed(() => reportSummaryData.value?.data ?? reportSummaryData.value ?? null)

const { data: monthlySummaryData } = useQuery({
  queryKey: ['daily-production-monthly-summary', monthlyYear, monthlyMonth],
  queryFn: () => dailyProductionApi.monthlySummary({ year: monthlyYear.value, month: monthlyMonth.value }) as Promise<any>,
  staleTime: 60_000,
})
const monthlySummary = computed(() => monthlySummaryData.value?.data ?? monthlySummaryData.value ?? null)

const deptSummaryColumns: TableColumn[] = [
  { field: 'department', header: '部门', align: 'center' },
  { field: 'total_quantity', header: '产量', align: 'center' },
  { field: 'total_value', header: '产值', align: 'center' },
  { field: 'sku_count', header: 'SKU', align: 'center' },
]
const dailyDetailColumns: TableColumn[] = [
  { field: 'day', header: '日期', align: 'center' },
  { field: 'filling', header: '充棉', align: 'center' },
  { field: 'handcraft', header: '手工', align: 'center' },
  { field: 'packaging', header: '包装', align: 'center' },
  { field: 'total', header: '合计', align: 'center' },
  { field: 'total_value', header: '总产值', align: 'center' },
]

// ===== 日期工具 =====
function prevMonth() { if (monthlyMonth.value === 1) { monthlyMonth.value = 12; monthlyYear.value-- } else { monthlyMonth.value-- } }
function nextMonth() { if (monthlyMonth.value === 12) { monthlyMonth.value = 1; monthlyYear.value++ } else { monthlyMonth.value++ } }
function toLocalDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
function todayLocal(): string { return toLocalDate(new Date()) }
function prevDay(d: string) { const dt = new Date(d + 'T00:00:00'); dt.setDate(dt.getDate() - 1); return toLocalDate(dt) }
function nextDay(d: string) { const dt = new Date(d + 'T00:00:00'); dt.setDate(dt.getDate() + 1); return toLocalDate(dt) }

function goPrevDay() { dateRef.value = prevDay(dateRef.value) }
function goNextDay() { dateRef.value = nextDay(dateRef.value) }
function goToday() { dateRef.value = todayLocal() }

// ===== 导出（带进度提示和重试） =====
const exportStatus = reactive({ show: false, message: '', type: 'info', icon: 'fas fa-spinner fa-spin' })

async function handleExport() {
  exportStatus.show = true
  exportStatus.type = 'info'
  exportStatus.icon = 'fas fa-circle-notch fa-spin'
  exportStatus.message = '正在导出报表...'

  let retries = 0
  const maxRetries = 2

  while (retries <= maxRetries) {
    try {
      await dailyProductionApi.export({ start_date: selectedDate.value, end_date: selectedDate.value })
      exportStatus.type = 'success'
      exportStatus.icon = 'fas fa-check-circle'
      exportStatus.message = '导出成功'
      const _t = setTimeout(() => { exportStatus.show = false }, 3000)
      _timers.push(_t)
      return
    } catch {
      retries++
      if (retries <= maxRetries) {
        exportStatus.message = `导出失败，正在重试 (${retries}/${maxRetries})...`
        await new Promise(r => setTimeout(r, 1000 * retries))
      } else {
        exportStatus.type = 'error'
        exportStatus.icon = 'fas fa-times-circle'
        exportStatus.message = '导出失败，请稍后重试'
        const _t = setTimeout(() => { exportStatus.show = false }, 5000)
        _timers.push(_t)
      }
    }
  }
}

// ===== 键盘快捷键 =====
const entryDrawerRef = ref<InstanceType<typeof ProductionEntryDrawer>>()
function handleKeydown(event: KeyboardEvent) {
  if (event.ctrlKey && (event.key === 'n' || event.key === 'N')) {
    event.preventDefault()
    if (!showEntryDrawer.value) showEntryDrawer.value = true
  }
  if (event.ctrlKey && event.key === 'Enter' && showEntryDrawer.value) {
    event.preventDefault()
    entryDrawerRef.value?.handleSubmit()
  }
  if (event.key === 'Escape' && showEntryDrawer.value) {
    entryDrawerRef.value?.closeEntryDrawer()
  }
  if (event.ctrlKey && ['1', '2'].includes(event.key)) {
    event.preventDefault()
    const tabs = ['daily', 'monthly'] as const
    const tab = tabs[parseInt(event.key) - 1]
    if (tab) viewTab.value = tab
  }
}

// ===== ECharts =====
const dailyChartRef = ref<HTMLElement | undefined>()
const monthlyChartRef = ref<HTMLElement | undefined>()
function setDailyChartRef(el: Element | null) {
  dailyChartRef.value = (el as HTMLElement | null) ?? undefined
}
function setMonthlyChartRef(el: Element | null) {
  monthlyChartRef.value = (el as HTMLElement | null) ?? undefined
}

useProductionCharts(
  reportSummary,
  monthlySummary,
  viewTab,
  dailyChartRef,
  monthlyChartRef,
)

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
  _timers.forEach(clearTimeout)
})
</script>

<style scoped>
.pr-container {
  width: 100%;
  padding: 0;
  margin: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* ===== 导出提示 ===== */
.pr-export-toast {
  position: fixed; top: 20px; right: 20px; z-index: 120;
  padding: 10px 18px; border-radius: 10px;
  font-size: 13px; font-weight: 600;
  display: flex; align-items: center; gap: 8px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
}
.pr-export-toast.info { background: #eff6ff; color: #1e40af; border: 1px solid #bfdbfe; }
.pr-export-toast.success { background: #f0fdf4; color: #15803d; border: 1px solid #bbf7d0; }
.pr-export-toast.error { background: #fef2f2; color: #dc2626; border: 1px solid #fecaca; }

.pr-toast-enter-active, .pr-toast-leave-active { transition: opacity 0.3s ease, transform 0.3s ease; }
.pr-toast-enter-from, .pr-toast-leave-to { opacity: 0; transform: translateX(20px); }

@media (max-width: 768px) {
  .pr-container { padding: 0; }
  .page-card-main { border-radius: 12px; }
}
</style>
