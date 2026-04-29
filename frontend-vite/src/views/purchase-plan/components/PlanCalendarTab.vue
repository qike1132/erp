<template>
  <div class="cal-tab">
    <div v-if="isLoading" class="cal-state"><UiSpinner /> 加载中...</div>
    <div v-else-if="isError" class="cal-state">
      <i class="fas fa-exclamation-circle" style="color:var(--color-danger-500)" /> 加载失败
      <a href="#" @click.prevent="refetch" style="color:var(--color-primary-500);margin-left:4px">重试</a>
    </div>
    <UiEmpty v-else-if="!hasData" description="本月暂无出货计划" />
    <div v-else class="cal-grid-wrap">
      <div class="cal-weekdays">
        <div v-for="w in weekdays" :key="w" class="cal-wd">{{ w }}</div>
      </div>
      <div class="cal-grid">
        <div
          v-for="cell in calendarCells"
          :key="cell.key"
          class="cal-cell"
          :class="{
            'cal-cell-empty': !cell.day,
            'cal-cell-today': cell.isToday,
            'cal-cell-weekend': cell.isWeekend,
            'cal-cell-has-data': cell.hasData,
          }"
          @click="cell.hasData && $emit('selectDate', cell.date)"
        >
          <div class="cal-cell-head">
            <span class="cal-day-num" :class="{ 'cal-day-today': cell.isToday }">{{ cell.day || '' }}</span>
            <span v-if="cell.hasData" class="cal-day-count">{{ cell.totalQty }}件</span>
          </div>
          <div v-if="cell.hasData" class="cal-cell-body">
            <div
              v-for="item in cell.topItems"
              :key="item.detail_id"
              class="cal-item"
              :class="`cal-item-${item.statusClass}`"
              @click.stop="$emit('viewPlan', item.plan_id)"
            >
              <span class="cal-item-name">{{ item.customer_name }}</span>
              <span class="cal-item-qty">{{ item.quantity }}件</span>
            </div>
            <div v-if="cell.moreCount > 0" class="cal-more">
              +{{ cell.moreCount }}更多
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { planApi } from '@/api'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'

const props = defineProps<{
  year: number
  month: number
  customerId: string
}>()

defineEmits<{
  selectDate: [date: string]
  viewPlan: [planId: number]
}>()

const weekdays = ['一', '二', '三', '四', '五', '六', '日']

const { data: monthlyData, isLoading, isError, refetch } = useQuery({
  queryKey: ['plan-monthly', () => props.year, () => props.month, () => props.customerId],
  queryFn: async () => {
    const p: any = { year: props.year, month: props.month }
    if (props.customerId) p.customer_id = Number(props.customerId)
    return (await planApi.monthly(p)) as any
  },
  staleTime: 30_000,
})

const todayStr = computed(() => new Date().toISOString().slice(0, 10))

function statusClass(s: string) {
  if (s === 'shipped') return 'done'
  if (s === 'partial') return 'partial'
  return 'pending'
}

const calendarCells = computed(() => {
  const y = props.year, m = props.month
  const daysInMonth = new Date(y, m, 0).getDate()
  const firstDayOfWeek = new Date(y, m - 1, 1).getDay()
  const mondayOffset = firstDayOfWeek === 0 ? 6 : firstDayOfWeek - 1

  const pbd = monthlyData.value?.plans_by_date ?? {}

  const cells: any[] = []

  for (let i = 0; i < mondayOffset; i++) {
    cells.push({ key: `empty-${i}`, day: 0, date: '', isToday: false, isWeekend: false, hasData: false, totalQty: 0, topItems: [], moreCount: 0 })
  }

  for (let d = 1; d <= daysInMonth; d++) {
    const dateStr = `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`
    const items = pbd[dateStr] as any[] | undefined
    const hasData = !!items?.length
    const dow = new Date(y, m - 1, d).getDay()
    const isWeekend = dow === 0 || dow === 6

    let totalQty = 0
    let topItems: any[] = []
    let moreCount = 0

    if (hasData && items) {
      for (const i of items) totalQty += Number(i.quantity || 0)
      const sorted = [...items].sort((a, b) => Number(b.quantity) - Number(a.quantity))
      const shown = sorted.slice(0, 3)
      topItems = shown.map(i => ({
        detail_id: i.detail_id || i.id,
        plan_id: i.plan_id,
        customer_name: i.customer_name,
        product_name: i.product_name,
        quantity: Number(i.quantity || 0),
        statusClass: statusClass(i.shipment_status),
      }))
      moreCount = sorted.length - 3
    }

    cells.push({
      key: dateStr,
      day: d,
      date: dateStr,
      isToday: dateStr === todayStr.value,
      isWeekend,
      hasData,
      totalQty,
      topItems,
      moreCount,
    })
  }

  const remainder = cells.length % 7
  if (remainder > 0) {
    for (let i = 0; i < 7 - remainder; i++) {
      cells.push({ key: `empty-end-${i}`, day: 0, date: '', isToday: false, isWeekend: false, hasData: false, totalQty: 0, topItems: [], moreCount: 0 })
    }
  }

  return cells
})

const hasData = computed(() => {
  const pbd = monthlyData.value?.plans_by_date ?? {}
  return Object.keys(pbd).length > 0
})
</script>

<style scoped>
.cal-tab { display: flex; flex-direction: column; gap: 12px; }
.cal-state {
  display: flex; align-items: center; justify-content: center;
  padding: 48px 0; color: var(--color-text-muted); gap: 8px;
}

.cal-grid-wrap {
  background: var(--color-surface-card);
  border-radius: var(--radius-card);
  border: 1px solid var(--color-border-light);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}

.cal-weekdays {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  background: var(--gradient-card-header);
  border-bottom: 1px solid var(--color-border-light);
}
.cal-wd {
  padding: 10px 0;
  text-align: center;
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--color-text-secondary);
  letter-spacing: 0.5px;
}

.cal-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
}

.cal-cell {
  min-height: 110px;
  border-right: 1px solid var(--color-border-light);
  border-bottom: 1px solid var(--color-border-light);
  padding: 6px 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  transition: background 0.15s;
  cursor: default;
}
.cal-cell:nth-child(7n) { border-right: none; }
.cal-cell-empty {
  background: var(--color-surface);
  min-height: 0;
}
.cal-cell-today {
  background: rgba(91, 141, 239, 0.04);
}
.cal-cell-has-data {
  cursor: pointer;
}
.cal-cell-has-data:hover {
  background: rgba(91, 141, 239, 0.06);
}
.cal-cell-weekend {
  background: rgba(255, 159, 67, 0.03);
}
.cal-cell-weekend.cal-cell-has-data:hover {
  background: rgba(255, 159, 67, 0.06);
}

.cal-cell-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 2px;
}
.cal-day-num {
  font-size: 0.82rem;
  font-weight: 700;
  color: var(--color-text);
  width: 24px; height: 24px;
  display: flex; align-items: center; justify-content: center;
  border-radius: 6px;
}
.cal-day-today {
  background: var(--gradient-primary);
  color: white;
  box-shadow: 0 2px 6px rgba(91, 141, 239, 0.3);
}
.cal-day-count {
  font-size: 0.6rem;
  font-weight: 700;
  color: var(--color-primary-500);
  background: var(--color-primary-50);
  padding: 1px 6px;
  border-radius: 4px;
}

.cal-cell-body {
  display: flex;
  flex-direction: column;
  gap: 3px;
  flex: 1;
  overflow: hidden;
}

.cal-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 3px 6px;
  border-radius: 4px;
  font-size: 0.65rem;
  cursor: pointer;
  transition: all 0.15s;
  gap: 4px;
  overflow: hidden;
}
.cal-item:hover {
  filter: brightness(0.95);
  transform: translateX(1px);
}
.cal-item-name {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}
.cal-item-qty {
  font-weight: 700;
  white-space: nowrap;
}

.cal-item-done {
  background: var(--color-success-50);
  color: var(--color-success-700);
  border-left: 2px solid var(--color-success-500);
}
.cal-item-partial {
  background: var(--color-warning-50);
  color: var(--color-warning-700);
  border-left: 2px solid var(--color-warning-500);
}
.cal-item-pending {
  background: var(--color-slate-50);
  color: var(--color-text-secondary);
  border-left: 2px solid var(--color-slate-300);
}

.cal-more {
  font-size: 0.6rem;
  color: var(--color-primary-500);
  font-weight: 600;
  padding: 1px 6px;
  cursor: pointer;
}
.cal-more:hover {
  text-decoration: underline;
}

@media (max-width: 1024px) {
  .cal-cell { min-height: 90px; padding: 4px 6px; }
  .cal-item { font-size: 0.6rem; padding: 2px 4px; }
}
@media (max-width: 768px) {
  .cal-cell { min-height: 70px; }
  .cal-day-count { display: none; }
}
</style>
