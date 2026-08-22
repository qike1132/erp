<template>
  <div class="m-page">
    <MobileNavBar title="生产报表" :show-back="true" />
    <div class="m-page-body">
      <MFilterChips v-model="viewTab" :chips="viewChips" />

      <div class="m-date-nav">
        <button class="m-date-btn" aria-label="上一页" @click="prevDate">&lsaquo;</button>
        <span class="m-date-text">{{ viewTab === 'monthly' ? `${monthlyYear}年${monthlyMonth}月` : selectedDate }}</span>
        <button class="m-date-btn" aria-label="下一页" @click="nextDate">&rsaquo;</button>
      </div>

      <div v-if="loading" class="m-center"><MSpinner size="lg" /></div>
      <template v-else-if="summary">
        <div class="m-kpi-row">
          <MStatCard :value="totalQuantity ?? 0" label="总产量" icon-bg="rgba(0,113,227,0.1)" />
          <MStatCard :value="fmtMoney(totalValue ?? 0)" label="总产值" icon-bg="rgba(48,209,88,0.1)" />
        </div>
        <div class="m-dept-grid">
          <MCard v-for="dept in departments" :key="dept.key" padded>
            <div class="m-dept-name">{{ dept.name }}</div>
            <div class="m-dept-val">{{ dept.quantity }}</div>
            <MProgress :value="dept.quantity" :max="totalQuantity || 1" animated />
          </MCard>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { dailyProductionApi } from '@/api'
import MobileNavBar from '@/mobile/layouts/components/MobileNavBar.vue'
import MFilterChips from '@/mobile/components/MFilterChips.vue'
import MStatCard from '@/mobile/components/MStatCard.vue'
import MCard from '@/mobile/components/MCard.vue'
import MProgress from '@/mobile/components/MProgress.vue'
import MSpinner from '@/mobile/components/MSpinner.vue'

const viewTab = ref('daily')
const viewChips = [{ label: '日报', value: 'daily' }, { label: '月报', value: 'monthly' }]
const selectedDate = ref(new Date().toISOString().slice(0, 10))
const monthlyYear = ref(new Date().getFullYear())
const monthlyMonth = ref(new Date().getMonth() + 1)
interface ProductionSummary {
  departments?: Array<{ department: string; department_label?: string; total_quantity?: number }>
  monthly_departments?: Array<{ department: string; department_label?: string; total_quantity?: number }>
  monthly_total_quantity?: number
  overall_quantity?: number
  monthly_total_value?: number
  overall_value?: number
  [key: string]: unknown
}

const summary = ref<ProductionSummary | null>(null)
const loading = ref(false)

const DEPARTMENT_LABELS: Record<string, string> = {
  filling: '充棉部',
  handcraft: '手工部',
  packaging: '包装部',
}

const departments = computed(() => {
  // 日报：summary.departments = [{ department, department_label, total_quantity, ... }]
  // 月报：summary.monthly_departments = [{ department, ... }]
  const list = viewTab.value === 'monthly'
    ? (summary.value?.monthly_departments || [])
    : (summary.value?.departments || [])
  return list.map((d: { department: string; department_label?: string; total_quantity?: number }) => {
    const key = d.department
    return {
      key,
      name: d.department_label || DEPARTMENT_LABELS[key] || key,
      quantity: d.total_quantity ?? 0,
    }
  })
})

const totalQuantity = computed(() => {
  if (viewTab.value === 'monthly') return summary.value?.monthly_total_quantity ?? 0
  return summary.value?.overall_quantity ?? 0
})
const totalValue = computed(() => {
  if (viewTab.value === 'monthly') return summary.value?.monthly_total_value ?? 0
  return summary.value?.overall_value ?? 0
})

function fmtMoney(v: number) {
  if (v >= 10000) return (v / 10000).toFixed(1) + '万'
  return v.toLocaleString()
}

function prevDate() {
  if (viewTab.value === 'monthly') {
    monthlyMonth.value--
    if (monthlyMonth.value < 1) { monthlyMonth.value = 12; monthlyYear.value-- }
  } else {
    const d = new Date(selectedDate.value); d.setDate(d.getDate() - 1); selectedDate.value = d.toISOString().slice(0, 10)
  }
}
function nextDate() {
  if (viewTab.value === 'monthly') {
    monthlyMonth.value++
    if (monthlyMonth.value > 12) { monthlyMonth.value = 1; monthlyYear.value++ }
  } else {
    const d = new Date(selectedDate.value); d.setDate(d.getDate() + 1); selectedDate.value = d.toISOString().slice(0, 10)
  }
}

async function loadDaily() {
  loading.value = true
  try { summary.value = await dailyProductionApi.dailySummary(selectedDate.value) as ProductionSummary } finally { loading.value = false }
}
async function loadMonthly() {
  loading.value = true
  try { summary.value = await dailyProductionApi.monthlySummary({ year: monthlyYear.value, month: monthlyMonth.value }) as ProductionSummary } finally { loading.value = false }
}

watch(viewTab, (v) => { if (v === 'daily') loadDaily(); else loadMonthly() })
watch(selectedDate, loadDaily)
watch([monthlyYear, monthlyMonth], loadMonthly)
onMounted(loadDaily)
</script>

<style scoped>
.m-page { display: flex; flex-direction: column; height: 100%; background: var(--m-bg-deep); }
.m-page-body { flex: 1; min-height: 0; overflow-y: auto; padding: var(--m-gap-md); padding-bottom: calc(var(--m-gap-lg) + var(--m-tabbar-safe)); -webkit-overflow-scrolling: touch; }
.m-center { display: flex; justify-content: center; padding: 48px 0; }
.m-date-nav { display: flex; align-items: center; justify-content: center; gap: 8px; margin-bottom: 12px; }
.m-date-btn { width: 32px; height: 32px; border: 1px solid rgba(0,0,0,0.08); border-radius: 8px; background: var(--m-bg-surface); font-size: 16px; cursor: pointer; display: flex; align-items: center; justify-content: center; font-family: inherit; }
.m-date-text { font-size: 15px; font-weight: 600; color: var(--m-text-primary); min-width: 120px; text-align: center; }
.m-kpi-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 16px; }
.m-dept-grid { display: flex; flex-direction: column; gap: 10px; }
.m-dept-name { font-size: 14px; font-weight: 600; color: var(--m-text-primary); margin-bottom: 4px; }
.m-dept-val { font-size: 20px; font-weight: 700; color: var(--m-text-primary); margin-bottom: 8px; font-variant-numeric: tabular-nums; }
</style>
