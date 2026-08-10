<template>
  <div class="m-page">
    <MobileNavBar title="出货计划" :show-back="true" />
    <div class="m-page-body">
      <!-- 月份导航 -->
      <div class="m-month-nav">
        <button class="m-date-btn" @click="prevMonth">&laquo;</button>
        <span class="m-month-text">{{ year }}年{{ String(month).padStart(2, '0') }}月</span>
        <button class="m-date-btn" @click="nextMonth">&raquo;</button>
      </div>

      <!-- 日期横滑选择器 -->
      <div class="m-date-scroll" ref="dateScrollRef">
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
              <span class="m-summary-label">已出货</span>
              <span class="m-summary-val m-summary-done">{{ fmtQty(dateShipped) }}</span>
            </div>
            <div class="m-summary-item">
              <span class="m-summary-label">剩余</span>
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
              <div :class="['m-item-dot', dotClass(p.shipment_status)]" />
            </template>
            <template #value>
              <div class="m-item-right">
                <span class="m-item-qty">{{ p.quantity }}件</span>
                <span class="m-item-sub">已出{{ p.shipped_qty }} | 剩{{ p.remaining_qty }}</span>
                <span :class="['m-item-status', statusClass(p.shipment_status)]">
                  {{ statusLabel(p.shipment_status) }}
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
const loading = ref(false)
const dateScrollRef = ref<HTMLElement>()

function todayStr() { return new Date().toISOString().slice(0, 10) }

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
      weekday: WDS[d.getDay()],
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
const dateShipped = computed(() => selectedPlans.value.reduce((s, p) => s + Number(p.shipped_qty || 0), 0))
const dateRemain = computed(() => dateTotal.value - dateShipped.value)
const datePct = computed(() => dateTotal.value > 0 ? Math.floor(dateShipped.value / dateTotal.value * 1000) / 10 : 0)

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
  const map: Record<string, string> = { shipped: '已出货', completed: '已出货', partial: '部分出货', pending: '待出货' }
  return map[status] || '待出货'
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
  loading.value = true
  try {
    const res = await planApi.monthly({ year: year.value, month: month.value }) as any
    plansByDate.value = res?.plans_by_date || {}
    // 若当前选中日期不在返回数据中且该月有数据，则选中第一个有数据的日期
    if (!plansByDate.value[selectedDate.value]) {
      const keys = Object.keys(plansByDate.value).sort()
      if (keys.length > 0) {
        selectedDate.value = keys[0]
      }
    }
  } catch {
    plansByDate.value = {}
  } finally {
    loading.value = false
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
