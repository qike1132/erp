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
      <MEmpty v-else-if="loadError" :title="loadError">
        <template #action>
          <button class="m-retry-btn" @click="retryLoad">重试</button>
        </template>
      </MEmpty>
      <template v-else-if="hasSummary">
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
      <MEmpty v-else title="暂无生产数据" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { toISODate } from '@/utils/format'
import { ref, computed, watch, onMounted } from 'vue'
import { dailyProductionApi } from '@/api'
import type { DailySummary, MonthlySummary } from '@/types'
import MobileNavBar from '@/mobile/layouts/components/MobileNavBar.vue'
import MFilterChips from '@/mobile/components/MFilterChips.vue'
import MStatCard from '@/mobile/components/MStatCard.vue'
import MCard from '@/mobile/components/MCard.vue'
import MProgress from '@/mobile/components/MProgress.vue'
import MSpinner from '@/mobile/components/MSpinner.vue'
import MEmpty from '@/mobile/components/MEmpty.vue'

const viewTab = ref('daily')
const viewChips = [{ label: '日报', value: 'daily' }, { label: '月报', value: 'monthly' }]
// F-FE-MOBILE-06：toISOString 按 UTC 切日，东八区 00:00–07:59 会取到昨天。
const selectedDate = ref(toISODate())
const monthlyYear = ref(new Date().getFullYear())
const monthlyMonth = ref(new Date().getMonth() + 1)
// 日报/月报响应直接复用 @/types 的 DTO（S12；原先本地 ProductionSummary 带索引签名，
// 把「日报无 monthly_* 字段、月报无 overall_* 字段」的类型缺口掩盖掉了）
const dailySummary = ref<DailySummary | null>(null)
const monthlySummary = ref<MonthlySummary | null>(null)
const loading = ref(false)
// 2026-10-17 审计 P1-29：接口失败此前静默空白；快速切日期/月份旧响应也会覆盖新数据
const loadError = ref('')
let dailySeq = 0
let monthlySeq = 0

const hasSummary = computed(() =>
  viewTab.value === 'monthly' ? !!monthlySummary.value : !!dailySummary.value,
)

const DEPARTMENT_LABELS: Record<string, string> = {
  filling: '充棉部',
  handcraft: '手工部',
  packaging: '包装部',
}

const departments = computed(() => {
  // 日报：DailySummary.departments；月报：MonthlySummary.monthly_departments
  const list = viewTab.value === 'monthly'
    ? (monthlySummary.value?.monthly_departments ?? [])
    : (dailySummary.value?.departments ?? [])
  return list.map((d) => {
    const key = d.department
    return {
      key,
      name: d.department_label || DEPARTMENT_LABELS[key] || key,
      quantity: d.total_quantity,
    }
  })
})

const totalQuantity = computed(() =>
  viewTab.value === 'monthly'
    ? (monthlySummary.value?.monthly_total_quantity ?? 0)
    : (dailySummary.value?.overall_quantity ?? 0),
)
const totalValue = computed(() =>
  viewTab.value === 'monthly'
    ? (monthlySummary.value?.monthly_total_value ?? 0)
    : (dailySummary.value?.overall_value ?? 0),
)

function fmtMoney(v: number) {
  if (v >= 10000) return (v / 10000).toFixed(1) + '万'
  return v.toLocaleString()
}

function prevDate() {
  if (viewTab.value === 'monthly') {
    monthlyMonth.value--
    if (monthlyMonth.value < 1) { monthlyMonth.value = 12; monthlyYear.value-- }
  } else {
    const d = new Date(selectedDate.value + 'T00:00:00'); d.setDate(d.getDate() - 1); selectedDate.value = toISODate(d)
  }
}
function nextDate() {
  if (viewTab.value === 'monthly') {
    monthlyMonth.value++
    if (monthlyMonth.value > 12) { monthlyMonth.value = 1; monthlyYear.value++ }
  } else {
    const d = new Date(selectedDate.value + 'T00:00:00'); d.setDate(d.getDate() + 1); selectedDate.value = toISODate(d)
  }
}

function errorText(e: unknown, fallback: string) {
  // 403 已由全局拦截器 toast；页面仍要有可理解状态与重试入口
  return (e as { response?: { status?: number } })?.response?.status === 403 ? '无查看权限' : fallback
}

async function loadDaily() {
  const seq = ++dailySeq
  loading.value = true
  loadError.value = ''
  try {
    const res = await dailyProductionApi.dailySummary(selectedDate.value)
    if (seq !== dailySeq) return // 旧日期响应后到，丢弃
    dailySummary.value = res
  } catch (e) {
    if (seq !== dailySeq) return
    dailySummary.value = null
    loadError.value = errorText(e, '日报加载失败，请点击重试')
  } finally {
    if (seq === dailySeq) loading.value = false
  }
}

async function loadMonthly() {
  const seq = ++monthlySeq
  loading.value = true
  loadError.value = ''
  try {
    const res = await dailyProductionApi.monthlySummary({ year: monthlyYear.value, month: monthlyMonth.value })
    if (seq !== monthlySeq) return // 旧月份响应后到，丢弃
    monthlySummary.value = res
  } catch (e) {
    if (seq !== monthlySeq) return
    monthlySummary.value = null
    loadError.value = errorText(e, '月报加载失败，请点击重试')
  } finally {
    if (seq === monthlySeq) loading.value = false
  }
}

/** 错误态重试：重发当前 tab 的请求 */
function retryLoad() {
  if (viewTab.value === 'monthly') void loadMonthly()
  else void loadDaily()
}

watch(viewTab, (v) => {
  // 切 tab 时作废另一侧在途请求，避免其 finally/catch 影响当前 tab 的 loading/错误态
  if (v === 'daily') { monthlySeq++; void loadDaily() }
  else { dailySeq++; void loadMonthly() }
})
watch(selectedDate, () => { void loadDaily() })
watch([monthlyYear, monthlyMonth], () => { void loadMonthly() })
onMounted(() => { void loadDaily() })
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
.m-retry-btn { margin-top: 12px; height: 36px; padding: 0 20px; border: none; border-radius: 10px; background: var(--m-accent); color: white; font-size: 14px; font-weight: 600; cursor: pointer; font-family: inherit; }
</style>
