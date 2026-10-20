<template>
  <div class="m-page">
    <MobileNavBar title="出货计划" :show-back="true" />
    <div class="m-page-body">
      <!-- 月份导航 -->
      <div class="m-month-nav">
        <button class="m-date-btn" aria-label="上一月" @click="prevMonth">&laquo;</button>
        <span class="m-month-text">{{ year }}年{{ String(month).padStart(2, '0') }}月</span>
        <button class="m-date-btn" aria-label="下一月" @click="nextMonth">&raquo;</button>
      </div>

      <!-- 日期横滑选择器 -->
      <div ref="dateScrollRef" class="m-date-scroll">
        <button
          v-for="d in dateList"
          :key="d.date"
          :class="['m-date-chip', { 'm-date-chip-active': selectedDate === d.date }]"
          @click="selectedDate = d.date"
        >
          <span class="m-date-chip-day">{{ d.day }}</span>
          <span class="m-date-chip-wd">{{ d.weekday }}</span>
          <span v-if="d.count > 0" class="m-date-chip-badge">{{ d.count }}</span>
        </button>
      </div>

      <!-- 加载中 -->
      <div v-if="loading" class="m-center"><MSpinner size="lg" /></div>

      <!-- 空态 -->
      <MEmpty v-else-if="loadError" :title="loadError" />
      <MEmpty v-else-if="!selectedPlans.length" title="该日期暂无出货计划" />

      <!-- 日期汇总卡片 -->
      <template v-else>
        <div class="m-summary-card">
          <div class="m-summary-row">
            <div class="m-summary-item">
              <span class="m-summary-label">计划总量</span>
              <span class="m-summary-val">{{ fmtQty(dateTotal) }}</span>
            </div>
            <div class="m-summary-item">
              <span class="m-summary-label">已生产</span>
              <span class="m-summary-val m-summary-done">{{ fmtQty(dateProduced) }}</span>
            </div>
            <div class="m-summary-item">
              <span class="m-summary-label">待生产</span>
              <span class="m-summary-val m-summary-remain">{{ fmtQty(dateRemain) }}</span>
            </div>
          </div>
          <div class="m-summary-progress">
            <div class="m-summary-bar">
              <div class="m-summary-fill" :style="{ width: datePct + '%' }" />
            </div>
            <span class="m-summary-pct">{{ datePct }}%</span>
          </div>
        </div>

        <!-- 计划列表 -->
        <MList>
          <MListItem
            v-for="p in selectedPlans"
            :key="p.detail_id"
            :title="p.customer_name || '—'"
            :subtitle="`${p.product_name || '—'} (${p.barcode || '—'})`"
          >
            <template #icon>
              <div :class="['m-item-dot', dotClass(statusOf(p))]" />
            </template>
            <template #value>
              <div class="m-item-right">
                <span class="m-item-qty">{{ p.quantity }}件</span>
                <span class="m-item-sub">已生产{{ p.produced_qty }} | 待生产{{ p.remaining_qty }}</span>
                <span :class="['m-item-status', statusClass(statusOf(p))]">
                  {{ statusLabel(statusOf(p)) }}
                </span>
              </div>
            </template>
          </MListItem>
        </MList>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { toISODate } from '@/utils/format'
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import { planApi } from '@/api'
import MobileNavBar from '@/mobile/layouts/components/MobileNavBar.vue'
import MList from '@/mobile/components/MList.vue'
import MListItem from '@/mobile/components/MListItem.vue'
import MEmpty from '@/mobile/components/MEmpty.vue'
import MSpinner from '@/mobile/components/MSpinner.vue'
import type { Plan } from '@/views/purchase-plan/components/types'

const WDS = ['日', '一', '二', '三', '四', '五', '六']

const now = new Date()
const year = ref(now.getFullYear())
const month = ref(now.getMonth() + 1)
const selectedDate = ref(todayStr())
const plansByDate = ref<Record<string, Plan[]>>({})
// F-FE-MOBILE-10：加载错误态（403/网络失败与「暂无数据」区分）
const loadError = ref('')

const loading = ref(false)
const dateScrollRef = ref<HTMLElement>()
// 2026-10-17 审计 P1-28：切月会连发请求，旧响应后到不得覆盖新月数据
let loadSeq = 0

// F-FE-MOBILE-06：toISOString 按 UTC 切日（东八区 00–08 点取到昨天）
function todayStr() { return toISODate() }

function prevMonth() {
  if (month.value === 1) { month.value = 12; year.value-- }
  else { month.value-- }
}
function nextMonth() {
  if (month.value === 12) { month.value = 1; year.value++ }
  else { month.value++ }
}

/** 仅生成有出货计划的日期条目（用于横滑选择器） */
const dateList = computed(() => {
  const days: { date: string; day: number; weekday: string; count: number }[] = []
  for (const ds of Object.keys(plansByDate.value).sort()) {
    const plans = plansByDate.value[ds] || []
    if (!plans.length) continue
    const d = new Date(ds + 'T00:00:00')
    days.push({
      date: ds,
      day: d.getDate(),
      weekday: WDS[d.getDay()] ?? '',
      count: plans.length,
    })
  }
  return days
})

/** 当前选中日期的计划列表 */
const selectedPlans = computed<Plan[]>(() => {
  return plansByDate.value[selectedDate.value] || []
})

/** 当前日期的汇总数据 */
const dateTotal = computed(() => selectedPlans.value.reduce((s, p) => s + Number(p.quantity || 0), 0))
const dateProduced = computed(() => selectedPlans.value.reduce((s, p) => s + Number(p.produced_qty || 0), 0))
const dateRemain = computed(() => dateTotal.value - dateProduced.value)
const datePct = computed(() => dateTotal.value > 0 ? Math.floor(dateProduced.value / dateTotal.value * 1000) / 10 : 0)

function fmtQty(n: number) { return String(n) }

function dotClass(status: string) {
  if (status === 'shipped' || status === 'completed') return 'm-dot-done'
  if (status === 'partial') return 'm-dot-partial'
  return 'm-dot-pending'
}

function statusClass(status: string) {
  if (status === 'shipped' || status === 'completed') return 'm-sts-done'
  if (status === 'partial') return 'm-sts-partial'
  return 'm-sts-pending'
}

function statusLabel(status: string) {
  const map: Record<string, string> = { shipped: '已生产', completed: '已生产', partial: '部分生产', pending: '待生产' }
  return map[status] || '待生产'
}

/** 该明细当日是否已生产达标。
    /plans/monthly 的 plans_by_date[] 不返回 shipment_status，原先直接读 p.shipment_status
    恒为 undefined、状态圆点与文案一直是「待出货」。改为就地由数量推导，规则同后端
    getShipmentStatus：产满为 completed、产了一部分为 partial、未产为 pending。 */
function statusOf(p: Plan): string {
  const qty = Number(p.quantity || 0)
  const produced = Number(p.produced_qty || 0)
  // 2026-10-17 审计 P2-62：与后端 calc_shipment_status 逐字对齐——
  // 后端是 shipped_qty >= plan_qty 即 completed（plan=0 时为 completed），
  // 此前的 qty>0 前置守卫会在边界值上与后端分叉。
  if (produced >= qty) return 'completed'
  if (produced > 0) return 'partial'
  return 'pending'
}

/** 自动滚动到选中日期 */
watch(selectedDate, async () => {
  await nextTick()
  if (!dateScrollRef.value) return
  const el = dateScrollRef.value.querySelector('.m-date-chip-active') as HTMLElement | null
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' })
  }
})

/** 加载月度数据（复用于 PurchasePlanView 的 /plans/monthly 接口） */
async function loadData() {
  const seq = ++loadSeq
  loading.value = true
  try {
    const res = await planApi.monthly({ year: year.value, month: month.value })
    if (seq !== loadSeq) return // 过期月份的响应直接丢弃
    plansByDate.value = (res?.plans_by_date ?? {}) as Record<string, Plan[]>
    loadError.value = ''
    // 若当前选中日期不在返回数据中且该月有数据，则选中第一个有数据的日期
    if (!plansByDate.value[selectedDate.value]) {
      const keys = Object.keys(plansByDate.value).sort()
      if (keys.length > 0) {
        selectedDate.value = keys[0] ?? ''
      }
    }
  } catch (e) {
    if (seq !== loadSeq) return
    plansByDate.value = {}
    // F-FE-MOBILE-10：403 等错误原先吞成空 plans → 页面显示「暂无计划」，
    // 与「真没数据」不可区分。置错误态让空态文案如实（403 详情拦截器已 toast）。
    // P2-7：本页无下拉刷新，文案不能说「下拉重试」。
    loadError.value = (e as { response?: { status?: number } })?.response?.status === 403
      ? '无查看权限'
      : '加载失败，请稍后重试'
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

watch([year, month], () => { loadData() })
onMounted(() => { loadData() })
</script>

<style scoped>
.m-page { display: flex; flex-direction: column; height: 100%; background: var(--m-bg-deep); }
.m-page-body { flex: 1; min-height: 0; overflow-y: auto; padding: var(--m-gap-md); padding-bottom: calc(var(--m-gap-lg) + var(--m-tabbar-safe)); -webkit-overflow-scrolling: touch; }
.m-center { display: flex; justify-content: center; padding: 48px 0; }

/* 月份导航 */
.m-month-nav {
  display: flex; align-items: center; justify-content: center; gap: 12px; margin-bottom: 10px;
}
.m-month-text {
  font-size: 16px; font-weight: 800; color: var(--m-text-primary); min-width: 120px; text-align: center; user-select: none;
}
.m-date-btn {
  width: 32px; height: 32px; border: 1px solid rgba(0,0,0,0.08); border-radius: 8px; background: var(--m-bg-surface);
  font-size: 16px; cursor: pointer; display: flex; align-items: center; justify-content: center; font-family: inherit;
  color: var(--m-text-primary);
}
.m-date-btn:active { background: var(--m-border-light); }

/* 日期横滑选择器 */
.m-date-scroll {
  display: flex; gap: 8px; overflow-x: auto; padding: 0 0 12px; -webkit-overflow-scrolling: touch; scrollbar-width: none;
}
.m-date-scroll::-webkit-scrollbar { display: none; }
.m-date-chip {
  display: flex; flex-direction: column; align-items: center; gap: 2px;
  min-width: 48px; padding: 8px 10px; border-radius: 12px;
  border: 1px solid var(--m-border-light); background: var(--m-bg-surface);
  cursor: pointer; flex-shrink: 0; position: relative; user-select: none;
  transition: background 0.2s, border-color 0.2s;
}
.m-date-chip-active {
  background: var(--m-accent); border-color: var(--m-accent);
}
.m-date-chip-active .m-date-chip-day,
.m-date-chip-active .m-date-chip-wd { color: white; }
.m-date-chip-active .m-date-chip-badge { background: rgba(255,255,255,0.3); color: white; }
.m-date-chip-day { font-size: 15px; font-weight: 700; color: var(--m-text-primary); line-height: 1; }
.m-date-chip-wd { font-size: 10px; font-weight: 500; color: var(--m-text-tertiary); }
.m-date-chip-badge {
  font-size: 10px; font-weight: 700; color: var(--m-accent); background: var(--m-accent-light);
  padding: 1px 6px; border-radius: 8px; margin-top: 2px;
}

/* 日期汇总卡片 */
.m-summary-card {
  margin-bottom: 14px; padding: 14px; border-radius: 14px;
  background: var(--m-bg-surface); border: 1px solid var(--m-border-light);
  box-shadow: 0 1px 4px rgba(0,0,0,0.04);
}
.m-summary-row {
  display: flex; justify-content: space-around; margin-bottom: 10px;
}
.m-summary-item {
  display: flex; flex-direction: column; align-items: center; gap: 2px;
}
.m-summary-label { font-size: 11px; color: var(--m-text-tertiary); }
.m-summary-val { font-size: 20px; font-weight: 800; color: var(--m-text-primary); font-variant-numeric: tabular-nums; }
.m-summary-done { color: var(--m-accent-emerald); }
.m-summary-remain { color: var(--m-accent-amber); }
.m-summary-progress { display: flex; align-items: center; gap: 8px; }
.m-summary-bar { flex: 1; height: 6px; border-radius: 3px; background: var(--m-border-light); overflow: hidden; }
.m-summary-fill {
  height: 100%; border-radius: 3px;
  background: linear-gradient(90deg, var(--m-accent-emerald), #34d399);
  transition: width 0.4s ease;
}
.m-summary-pct { font-size: 12px; font-weight: 700; color: var(--m-text-secondary); min-width: 36px; text-align: right; }

/* 计划列表项 */
.m-item-dot {
  width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0;
}
.m-dot-done { background: var(--m-accent-emerald); }
.m-dot-partial { background: var(--m-accent-amber); }
.m-dot-pending { background: var(--m-text-tertiary); }

.m-item-right {
  display: flex; flex-direction: column; align-items: flex-end; gap: 2px;
}
.m-item-qty { font-size: 15px; font-weight: 700; color: var(--m-text-primary); }
.m-item-sub { font-size: 11px; color: var(--m-text-tertiary); }
.m-item-status { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 6px; }
.m-sts-done { background: rgba(16, 185, 129, 0.1); color: #059669; }
.m-sts-partial { background: rgba(245, 158, 11, 0.1); color: #d97706; }
.m-sts-pending { background: rgba(148, 163, 184, 0.1); color: #64748b; }
</style>
