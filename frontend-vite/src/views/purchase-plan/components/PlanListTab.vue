<template>
  <div class="sch-tab">
    <div v-if="isLoading" class="sch-state"><UiSpinner /> 加载中...</div>
    <div v-else-if="isError" class="sch-state">
      <i class="fas fa-exclamation-circle" style="color:var(--color-danger-500)" /> 加载失败
      <a href="#" @click.prevent="refetch" style="color:var(--color-primary-500);margin-left:4px">重试</a>
    </div>
    <UiEmpty v-else-if="!hasData" description="本月暂无出货计划" />

    <div v-else class="sch-list">
      <div v-for="g in dateGroups" :key="g.date" class="sch-group" :class="{ 'sch-group-today': g.isToday }">
        <div class="sch-group-head" @click="toggleGroup(g.date)">
          <div class="sch-group-left">
            <div class="sch-date-badge" :class="{ 'sch-date-today': g.isToday }">
              <span class="sch-date-day">{{ g.day }}</span>
            </div>
            <div class="sch-date-info">
              <span class="sch-date-weekday">{{ g.weekday }}</span>
              <span v-if="g.isToday" class="sch-today-tag">今日</span>
            </div>
            <div class="sch-group-chips">
              <span class="sch-chip sch-chip-customer"><b>{{ g.customerCount }}</b>客户</span>
              <span class="sch-chip sch-chip-product"><b>{{ g.productCount }}</b>产品</span>
              <span class="sch-chip sch-chip-qty"><b>{{ g.totalQty }}</b>件</span>
              <span v-if="g.shippedQty" class="sch-chip sch-chip-shipped">已出{{ g.shippedQty }}</span>
              <span v-if="g.remainingQty" class="sch-chip sch-chip-remaining">待出{{ g.remainingQty }}</span>
            </div>
          </div>
          <div class="sch-group-right">
            <div class="sch-mini-progress">
              <div class="sch-mini-bar">
                <div class="sch-mini-fill" :style="{ width: gRate(g) + '%' }" :class="gRate(g) >= 100 ? 'sch-fill-done' : ''" />
              </div>
              <span class="sch-mini-pct">{{ gRate(g) }}%</span>
            </div>
            <i class="fas fa-chevron-down sch-expand-icon" :class="{ 'sch-expand-open': expandedGroups.has(g.date) }" />
          </div>
        </div>

        <div v-if="expandedGroups.has(g.date)" class="sch-group-body">
          <table class="sch-table">
            <thead>
              <tr>
                <th>客户名称</th>
                <th>产品名称</th>
                <th>条码</th>
                <th class="sch-th-num">数量</th>
                <th class="sch-th-num">已出</th>
                <th class="sch-th-num">待出</th>
                <th class="sch-th-status">状态</th>
                <th class="sch-th-action">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in g.items" :key="item.detail_id" class="sch-row">
                <td class="sch-td-customer">{{ item.customer_name }}</td>
                <td class="sch-td-product">{{ item.product_name }}</td>
                <td class="sch-td-barcode">{{ item.barcode || '—' }}</td>
                <td class="sch-td-num"><b>{{ item.quantity }}</b></td>
                <td class="sch-td-num">
                  <span :class="item.shipped_qty ? 'sch-c-green' : 'sch-c-muted'">{{ item.shipped_qty || 0 }}</span>
                </td>
                <td class="sch-td-num">
                  <span :class="item.remaining_qty ? 'sch-c-orange' : 'sch-c-muted'">{{ item.remaining_qty || 0 }}</span>
                </td>
                <td class="sch-td-status">
                  <span class="sch-status" :class="statusCls(item.shipment_status)">{{ statusTxt(item.shipment_status) }}</span>
                </td>
                <td class="sch-td-action">
                  <button class="sch-action-btn" title="查看详情" @click="$emit('viewPlan', item.plan_id)">
                    <i class="fas fa-eye" />
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, computed, ref } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { planApi } from '@/api'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'

const props = defineProps<{
  year: number
  month: number
  customerId: string
  status: string
}>()

defineEmits<{
  viewPlan: [planId: number]
  editPlan: [planId: number]
}>()

const expandedGroups = ref(new Set<string>())

function toggleGroup(date: string) {
  if (expandedGroups.value.has(date)) {
    expandedGroups.value.delete(date)
  } else {
    expandedGroups.value.add(date)
  }
}

const { data: monthlyData, isLoading, isError, refetch } = useQuery({
  queryKey: ['plan-monthly-schedule', () => props.year, () => props.month, () => props.customerId],
  queryFn: async () => {
    const p: any = { year: props.year, month: props.month }
    if (props.customerId) p.customer_id = Number(props.customerId)
    return (await planApi.monthly(p)) as any
  },
  staleTime: 30_000,
})

const WD = ['日', '一', '二', '三', '四', '五', '六']
const todayStr = computed(() => new Date().toISOString().slice(0, 10))

const dateGroups = computed(() => {
  const pbd = monthlyData.value?.plans_by_date ?? {}
  const groups: any[] = []
  for (const [dateStr, items] of Object.entries(pbd)) {
    const arr = items as any[]
    if (!arr?.length) continue
    const d = new Date(dateStr + 'T00:00:00')
    let totalQty = 0, shippedQty = 0, remainingQty = 0
    const cs = new Set<string>(), ps = new Set<string>()
    for (const i of arr) {
      totalQty += Number(i.quantity || 0)
      shippedQty += Number(i.shipped_qty || 0)
      remainingQty += Number(i.remaining_qty || 0)
      if (i.customer_name) cs.add(i.customer_name)
      if (i.product_name) ps.add(i.product_name)
    }
    groups.push({
      date: dateStr, day: d.getDate(), weekday: `周${WD[d.getDay()]}`,
      isToday: dateStr === todayStr.value,
      items: arr, customerCount: cs.size, productCount: ps.size,
      totalQty, shippedQty, remainingQty,
    })
  }

  for (const g of groups) {
    if (g.isToday) {
      expandedGroups.value.add(g.date)
    }
  }

  return groups.sort((a, b) => a.date.localeCompare(b.date))
})

const hasData = computed(() => dateGroups.value.length > 0)

function gRate(g: any) {
  return g.totalQty ? Math.round(g.shippedQty / g.totalQty * 100) : 0
}
function statusCls(s: string) {
  if (s === 'shipped') return 'sch-st-done'
  if (s === 'partial') return 'sch-st-partial'
  return 'sch-st-pending'
}
function statusTxt(s: string) {
  if (s === 'shipped') return '已出货'
  if (s === 'partial') return '部分出货'
  return '待出货'
}
</script>

<style scoped>
.sch-tab { display: flex; flex-direction: column; gap: 10px; }
.sch-state {
  display: flex; align-items: center; justify-content: center;
  padding: 48px 0; color: var(--color-text-muted); gap: 8px;
}

.sch-list { display: flex; flex-direction: column; gap: 8px; }

.sch-group {
  background: var(--color-surface-card);
  border-radius: var(--radius-card);
  border: 1px solid var(--color-border-light);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
.sch-group:hover {
  box-shadow: var(--shadow-md);
}
.sch-group-today {
  border-left: 3px solid var(--color-primary-500);
}

.sch-group-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  cursor: pointer;
  transition: background 0.15s;
  gap: 12px;
}
.sch-group-head:hover {
  background: rgba(91, 141, 239, 0.03);
}

.sch-group-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

.sch-date-badge {
  width: 42px; height: 42px;
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  border: 1px solid var(--color-border-light);
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.sch-date-day {
  font-size: 1.1rem;
  font-weight: 900;
  color: var(--color-text);
  line-height: 1;
}
.sch-date-today {
  background: var(--gradient-primary);
  border: none;
  box-shadow: 0 2px 8px rgba(91, 141, 239, 0.3);
}
.sch-date-today .sch-date-day { color: white; }

.sch-date-info {
  display: flex; flex-direction: column; align-items: center; gap: 2px;
  flex-shrink: 0;
}
.sch-date-weekday {
  font-size: 0.75rem; font-weight: 600; color: var(--color-text-secondary);
}
.sch-today-tag {
  font-size: 0.5rem; font-weight: 800; letter-spacing: 0.5px;
  color: white; background: var(--color-primary-500);
  padding: 1px 6px; border-radius: 4px;
}

.sch-group-chips {
  display: flex; gap: 6px; flex-wrap: wrap; align-items: center;
}
.sch-chip {
  display: inline-flex; align-items: center; gap: 2px;
  font-size: 0.7rem; font-weight: 600;
  padding: 2px 8px; border-radius: 6px;
  color: var(--color-text-secondary);
  background: var(--color-slate-50);
  border: 1px solid var(--color-border-light);
}
.sch-chip b { font-weight: 800; color: var(--color-text); margin-right: 1px; }
.sch-chip-qty { background: var(--color-primary-50); border-color: var(--color-primary-100); color: var(--color-primary-600); }
.sch-chip-qty b { color: var(--color-primary-500); }
.sch-chip-shipped { background: var(--color-success-50); border-color: var(--color-success-100); color: var(--color-success-600); }
.sch-chip-shipped b { color: var(--color-success-500); }
.sch-chip-remaining { background: var(--color-warning-50); border-color: var(--color-warning-100); color: var(--color-warning-600); }
.sch-chip-remaining b { color: var(--color-warning-500); }

.sch-group-right {
  display: flex; align-items: center; gap: 12px; flex-shrink: 0;
}
.sch-mini-progress {
  display: flex; align-items: center; gap: 6px;
}
.sch-mini-bar {
  width: 48px; height: 6px;
  border-radius: 3px;
  background: var(--color-border-light);
  overflow: hidden;
}
.sch-mini-fill {
  height: 100%; border-radius: 3px;
  background: var(--gradient-primary);
  transition: width 0.4s;
}
.sch-fill-done {
  background: var(--gradient-success);
}
.sch-mini-pct {
  font-size: 0.68rem; font-weight: 700; color: var(--color-text-secondary);
  min-width: 32px;
}
.sch-expand-icon {
  font-size: 0.7rem;
  color: var(--color-text-muted);
  transition: transform 0.3s;
}
.sch-expand-open {
  transform: rotate(180deg);
}

.sch-group-body {
  border-top: 1px solid var(--color-border-light);
  overflow-x: auto;
}

.sch-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.82rem;
  min-width: 640px;
}
.sch-table thead th {
  padding: 10px 14px;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.5px;
  color: var(--color-text-secondary);
  background: var(--gradient-card-header);
  border-bottom: 1px solid var(--color-border-light);
  text-align: left;
  white-space: nowrap;
}
.sch-th-num, .sch-th-status, .sch-th-action { text-align: center; }

.sch-row td {
  padding: 8px 14px;
  border-bottom: 1px solid var(--color-border-light);
}
.sch-row:last-child td { border-bottom: none; }
.sch-row:hover { background: rgba(91, 141, 239, 0.03); }

.sch-td-customer { font-weight: 700; color: var(--color-text); }
.sch-td-product {
  color: var(--color-text);
  max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.sch-td-barcode {
  font-family: var(--font-mono); font-size: 0.72rem;
  color: var(--color-text-muted);
}
.sch-td-num { text-align: center; }
.sch-td-num b { font-weight: 800; color: var(--color-text); }

.sch-c-green { color: var(--color-success-500); font-weight: 600; }
.sch-c-orange { color: var(--color-warning-500); font-weight: 600; }
.sch-c-muted { color: var(--color-text-muted); }

.sch-td-status { text-align: center; }
.sch-status {
  display: inline-block; padding: 2px 10px;
  border-radius: 6px; font-size: 0.68rem; font-weight: 600;
}
.sch-st-done { background: var(--color-success-50); color: var(--color-success-600); }
.sch-st-partial { background: var(--color-warning-50); color: var(--color-warning-600); }
.sch-st-pending { background: var(--color-slate-50); color: var(--color-text-secondary); }

.sch-td-action { text-align: center; }
.sch-action-btn {
  width: 28px; height: 28px;
  border-radius: 6px;
  border: 1px solid var(--color-border-light);
  background: var(--color-surface-card);
  cursor: pointer;
  display: inline-flex; align-items: center; justify-content: center;
  color: var(--color-text-secondary);
  font-size: 0.7rem;
  transition: all 0.2s;
}
.sch-action-btn:hover {
  border-color: var(--color-primary-500);
  color: var(--color-primary-500);
  background: var(--color-primary-50);
}

@media (max-width: 768px) {
  .sch-group-chips { display: none; }
  .sch-group-head { padding: 10px 12px; }
  .sch-date-badge { width: 36px; height: 36px; }
  .sch-date-day { font-size: 0.95rem; }
}
</style>
