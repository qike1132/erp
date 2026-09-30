<template>
  <div class="page-card page-card-main m-0 h-full">
    <ProductionToolbar
      v-model:date="selectedDate"
      @prev-day="goPrevDay"
      @next-day="goNextDay"
      @today="goToday"
      @open-entry="entryOpen = true"
      @open-records="openRecordsFor('')"
      @export="handleExport"
    />

    <div class="page-card-body flex flex-col gap-3">
      <CockpitKpiRow
        data-test="cockpit-kpi"
        :today="todaySummary"
        :yesterday="yesterdaySummary"
        :monthly="monthlySummary"
        :previous-month="previousMonthSummary"
      />

      <div class="grid min-h-0 grid-cols-1 gap-3 xl:grid-cols-[2fr_1fr]">
        <ProductionTrendPanel data-test="cockpit-trend" :trend="trendData" :loading="trendLoading" />
        <DeptRankPanel data-test="cockpit-rank" :departments="monthlySummary?.monthly_departments ?? []" :loading="monthlyLoading" />
      </div>

      <DeptDrillCards
        data-test="cockpit-dept-cards"
        :departments="todaySummary?.departments ?? []"
        :loading="dailyLoading"
        @drill="openRecordsFor"
      />
    </div>

    <RecordDrawer
      v-model:open="recordsOpen"
      :filters="recordsFilters"
      :records="recordsQuery.data.value?.data ?? []"
      :total="recordsQuery.data.value?.total ?? 0"
      :stats="recordsQuery.data.value?.stats ?? null"
      :loading="recordsQuery.isFetching.value"
      :departments="visibleDepartments"
      :created-by-options="createdByOptions"
      @update:filters="recordsFilters = $event"
      @search="onRecordsSearch"
      @edit="openEdit"
      @confirm-delete="onConfirmDelete"
    />

    <RecordEditDialog v-model:open="editOpen" :record="editingRecord" @saved="onRecordSaved" />

    <ProductionEntryDialog ref="entryDialogRef" v-model:open="entryOpen" v-model:selected-date="selectedDate" />

    <Transition name="pr-toast">
      <div v-if="exportStatus.show" :class="['pr-export-toast', exportStatus.type]">
        <span>{{ exportStatus.message }}</span>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useQuery } from '@tanstack/vue-query'

import { dailyProductionApi } from '@/api/production'
import { showToast } from '@/composables/useToast'
import type { DailyProductionRecord, DailySummary, MonthlySummary } from '@/types'
import ProductionToolbar from './components/ProductionToolbar.vue'
import CockpitKpiRow from './components/CockpitKpiRow.vue'
import ProductionTrendPanel from './components/ProductionTrendPanel.vue'
import DeptRankPanel from './components/DeptRankPanel.vue'
import DeptDrillCards from './components/DeptDrillCards.vue'
import RecordDrawer from './components/RecordDrawer.vue'
import RecordEditDialog from './components/RecordEditDialog.vue'
import ProductionEntryDialog from './components/ProductionEntryDialog.vue'
import { useProductionTrend } from './composables/useProductionTrend'
import { useProductionRecords } from './composables/useProductionRecords'
import { defaultRecordFilters, type RecordFilters } from './composables/recordFilters'
import { toLocalDate } from './composables/productionDate'

const TREND_DAYS = ref(30)

const selectedDate = ref(toLocalDate(new Date()))
const entryOpen = ref(false)
const editOpen = ref(false)
const editingRecord = ref<DailyProductionRecord | null>(null)
const recordsOpen = ref(false)
const recordsFilters = ref<RecordFilters>(defaultRecordFilters())
const entryDialogRef = ref<InstanceType<typeof ProductionEntryDialog>>()

function goPrevDay() {
  const d = new Date(`${selectedDate.value}T00:00:00`)
  d.setDate(d.getDate() - 1)
  selectedDate.value = toLocalDate(d)
}
function goNextDay() {
  const d = new Date(`${selectedDate.value}T00:00:00`)
  d.setDate(d.getDate() + 1)
  selectedDate.value = toLocalDate(d)
}
function goToday() {
  selectedDate.value = toLocalDate(new Date())
}

// ===== 三个数据源 =====
const { data: dailyData, isFetching: dailyLoading } = useQuery({
  queryKey: computed(() => ['daily-production-daily-summary', selectedDate.value]),
  queryFn: () => dailyProductionApi.dailySummary(selectedDate.value),
  staleTime: 30_000,
})
const todaySummary = computed<DailySummary | null>(() => dailyData.value ?? null)

const yesterdayDate = computed(() => {
  const d = new Date(`${selectedDate.value}T00:00:00`)
  d.setDate(d.getDate() - 1)
  return toLocalDate(d)
})
const { data: yesterdayData } = useQuery({
  queryKey: computed(() => ['daily-production-daily-summary', yesterdayDate.value]),
  queryFn: () => dailyProductionApi.dailySummary(yesterdayDate.value),
  staleTime: 30_000,
})
const yesterdaySummary = computed<DailySummary | null>(() => yesterdayData.value ?? null)

const { data: monthlyData, isFetching: monthlyLoading } = useQuery({
  queryKey: computed(() => [
    'daily-production-monthly-summary',
    new Date(`${selectedDate.value}T00:00:00`).getFullYear(),
    new Date(`${selectedDate.value}T00:00:00`).getMonth() + 1,
  ]),
  queryFn: () =>
    dailyProductionApi.monthlySummary({
      year: new Date(`${selectedDate.value}T00:00:00`).getFullYear(),
      month: new Date(`${selectedDate.value}T00:00:00`).getMonth() + 1,
    }),
  staleTime: 60_000,
})
const monthlySummary = computed<MonthlySummary | null>(() => monthlyData.value ?? null)

/** 上月汇总：只用于 KPI 条的"日均较上月"。跨年时月份回绕到 12 月、年份减一。 */
const previousMonthParts = computed(() => {
  const d = new Date(`${selectedDate.value}T00:00:00`)
  const year = d.getMonth() === 0 ? d.getFullYear() - 1 : d.getFullYear()
  const month = d.getMonth() === 0 ? 12 : d.getMonth()
  return { year, month }
})
const { data: previousMonthData } = useQuery({
  queryKey: computed(() => ['daily-production-monthly-summary', previousMonthParts.value.year, previousMonthParts.value.month]),
  queryFn: () => dailyProductionApi.monthlySummary(previousMonthParts.value),
  staleTime: 60_000,
})
const previousMonthSummary = computed<MonthlySummary | null>(() => previousMonthData.value ?? null)

const { trendQuery } = useProductionTrend(TREND_DAYS)
const trendData = computed(() => trendQuery.data.value ?? null)
const trendLoading = computed(() => trendQuery.isFetching.value)

const { recordsQuery, removeRecord } = useProductionRecords(recordsFilters)

/** 可见部门：优先用今日汇总返回的（它已按权限收窄），否则回落到趋势返回的 */
const visibleDepartments = computed(() => {
  const fromDaily = todaySummary.value?.departments.map((d) => d.department)
  if (fromDaily?.length) return fromDaily
  return trendData.value?.departments ?? []
})

/** 录单人下拉的可选值：从当前页记录里去重（后端没有独立的录单人字典接口） */
const createdByOptions = computed(() => {
  const names = new Set<string>()
  for (const r of recordsQuery.data.value?.data ?? []) {
    if (r.created_by) names.add(r.created_by)
  }
  return [...names].sort().map((n) => ({ label: n, value: n }))
})

function openRecordsFor(department: string) {
  recordsFilters.value = { ...recordsFilters.value, department, page: 1 }
  recordsOpen.value = true
}

function onRecordsSearch() {
  recordsFilters.value = { ...recordsFilters.value, page: 1 }
}

function openEdit(record: DailyProductionRecord) {
  editingRecord.value = record
  editOpen.value = true
}

function onRecordSaved() {
  showToast('保存成功', 'success')
}

async function onConfirmDelete(id: number) {
  try {
    await removeRecord.mutateAsync(id)
    showToast('已删除', 'success')
  } catch {
    showToast('删除失败', 'error')
  }
}

// ===== 导出 =====
const exportStatus = reactive({ show: false, message: '', type: 'info' })
let exportTimer: ReturnType<typeof setTimeout> | undefined

async function handleExport() {
  exportStatus.show = true
  exportStatus.type = 'info'
  exportStatus.message = '正在导出报表…'
  try {
    await dailyProductionApi.export({ start_date: selectedDate.value, end_date: selectedDate.value })
    exportStatus.type = 'success'
    exportStatus.message = '导出成功'
  } catch {
    exportStatus.type = 'error'
    exportStatus.message = '导出失败，请稍后重试'
  }
  exportTimer = setTimeout(() => {
    exportStatus.show = false
  }, 3000)
}

// ===== 键盘快捷键：Ctrl+N 打开录入、Ctrl+Enter 提交、Esc 关闭录入弹窗 =====
// 弹窗内部仍印着这三个快捷键的提示，故编排层必须真的接线（它 defineExpose 了
// handleSubmit / closeEntryDrawer）。原来的 Ctrl+1/Ctrl+2 是给已删除的双 Tab 用的，不再需要。
function handleKeydown(event: KeyboardEvent) {
  if (event.ctrlKey && (event.key === 'n' || event.key === 'N')) {
    event.preventDefault()
    if (!entryOpen.value) entryOpen.value = true
  }
  if (event.ctrlKey && event.key === 'Enter' && entryOpen.value) {
    event.preventDefault()
    entryDialogRef.value?.handleSubmit()
  }
  if (event.key === 'Escape' && entryOpen.value) {
    entryDialogRef.value?.closeEntryDrawer()
  }
}

onMounted(() => window.addEventListener('keydown', handleKeydown))

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
  clearTimeout(exportTimer)
})

defineExpose({ openRecordsFor, recordsOpen, recordsFilters })
</script>

<style scoped>
.pr-export-toast {
  position: fixed;
  top: 20px;
  right: 20px;
  z-index: 120;
  padding: 10px 18px;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 600;
}
.pr-export-toast.info { background: var(--color-primary-50); color: var(--color-primary-700); }
.pr-export-toast.success { background: var(--color-success-50); color: var(--color-success-700); }
.pr-export-toast.error { background: var(--color-danger-50); color: var(--color-danger-700); }
.pr-toast-enter-active, .pr-toast-leave-active { transition: opacity 0.3s ease; }
.pr-toast-enter-from, .pr-toast-leave-to { opacity: 0; }
</style>
