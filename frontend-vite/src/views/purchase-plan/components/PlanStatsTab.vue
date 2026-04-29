<template>
  <div class="stat-tab">
    <div v-if="summaryData" class="stat-cards">
      <UiStatCard accent="blue">
        <template #label>计划总数</template>
        {{ summaryData.total_plan_qty }}
      </UiStatCard>
      <UiStatCard accent="ocean">
        <template #label>库存总量</template>
        {{ summaryData.total_inventory_qty }}
      </UiStatCard>
      <UiStatCard accent="green">
        <template #label>已出货</template>
        <template #extra>{{ shippedRate }}%</template>
        {{ summaryData.total_shipped_qty }}
      </UiStatCard>
      <UiStatCard accent="amber">
        <template #label>待出货</template>
        {{ summaryData.total_remaining_qty }}
      </UiStatCard>
    </div>

    <UiCard>
      <template #header>
        <div class="stat-card-header">
          <span class="stat-card-title">
            <i class="fas fa-users" style="margin-right: 6px; color: var(--color-primary-500)" />
            客户汇总
          </span>
          <span class="stat-record-count">共 {{ customerList.length }} 个客户</span>
        </div>
      </template>

      <div v-if="isLoadingSummary" class="stat-loading">
        <UiSpinner /> <span style="margin-left: 8px; color: var(--color-text-muted)">加载中...</span>
      </div>
      <UiEmpty v-else-if="customerList.length === 0" description="暂无汇总数据" />
      <div v-else class="stat-table-wrap">
        <table class="stat-table">
          <thead>
            <tr>
              <th>客户</th>
              <th class="stat-th-num">计划数量</th>
              <th class="stat-th-num">库存数量</th>
              <th class="stat-th-num">已出货</th>
              <th class="stat-th-num">待出货</th>
              <th class="stat-th-num">出货率</th>
              <th class="stat-th-center">缺货预警</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in customerList" :key="row.customer_id">
              <td class="stat-td-customer">{{ row.customer_name }}</td>
              <td class="stat-td-num">{{ row.plan_qty }}</td>
              <td class="stat-td-num">{{ row.inventory_qty }}</td>
              <td class="stat-td-num stat-text-success">{{ row.shipped_qty }}</td>
              <td class="stat-td-num">
                <span :class="{ 'stat-text-danger': row.remaining_qty > 0 }">{{ row.remaining_qty }}</span>
              </td>
              <td class="stat-td-num">
                <div class="stat-rate-cell">
                  <div class="stat-rate-bar">
                    <div
                      class="stat-rate-fill"
                      :class="row.plan_qty > 0 && row.shipped_qty >= row.plan_qty ? 'stat-rate-done' : ''"
                      :style="{ width: (row.plan_qty > 0 ? Math.round((row.shipped_qty / row.plan_qty) * 100) : 0) + '%' }"
                    />
                  </div>
                  <span class="stat-rate-text">{{ row.plan_qty > 0 ? Math.round((row.shipped_qty / row.plan_qty) * 100) : 0 }}%</span>
                </div>
              </td>
              <td class="stat-td-center">
                <span v-if="row.warning_count > 0" class="notification-badge">{{ row.warning_count }}</span>
                <span v-else class="stat-text-muted">-</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </UiCard>

    <UiCard>
      <template #header>
        <div class="stat-card-header">
          <span class="stat-card-title">
            <i class="fas fa-calendar-alt" style="margin-right: 6px; color: var(--color-primary-500)" />
            按日期累计汇总
          </span>
          <UiSelect
            v-model="selectedCustomerId"
            placeholder="全部客户"
            :options="customerFilterOptions"
            style="width: 160px"
          />
        </div>
      </template>

      <div v-if="isLoadingMonthly" class="stat-loading">
        <UiSpinner /> <span style="margin-left: 8px; color: var(--color-text-muted)">加载中...</span>
      </div>
      <UiEmpty v-else-if="dateRows.length === 0" description="当月暂无计划数据" />
      <div v-else class="stat-table-wrap">
        <table class="stat-table">
          <thead>
            <tr>
              <th>日期</th>
              <th class="stat-th-num">当日计划</th>
              <th class="stat-th-num">累计计划</th>
              <th class="stat-th-num">当日出货</th>
              <th class="stat-th-num">累计出货</th>
              <th class="stat-th-num">累计待出</th>
              <th style="width: 180px">出货进度</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in dateRows" :key="row.date">
              <td>
                <span class="stat-date-cell">{{ row.date }}</span>
                <span class="stat-weekday">{{ row.weekday }}</span>
              </td>
              <td class="stat-td-num">{{ row.dayPlanQty }}</td>
              <td class="stat-td-num stat-fw-semibold">{{ row.cumPlanQty }}</td>
              <td class="stat-td-num stat-text-success">{{ row.dayShippedQty }}</td>
              <td class="stat-td-num stat-text-success">{{ row.cumShippedQty }}</td>
              <td class="stat-td-num">
                <span :class="{ 'stat-text-danger': row.cumRemaining > 0 }">{{ row.cumRemaining }}</span>
              </td>
              <td>
                <UiProgress
                  :percentage="row.cumPlanQty > 0 ? Math.round((row.cumShippedQty / row.cumPlanQty) * 100) : 0"
                  :status="row.cumPlanQty > 0 && row.cumShippedQty >= row.cumPlanQty ? 'success' : 'primary'"
                  show-text
                />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { planApi } from '@/api'
import UiCard from '@/components/ui/UiCard.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiStatCard from '@/components/ui/UiStatCard.vue'
import UiProgress from '@/components/ui/UiProgress.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'

const props = defineProps<{ year: number; month: number }>()

const selectedCustomerId = ref('')

const { data: summaryData, isLoading: isLoadingSummary } = useQuery({
  queryKey: ['plan-customer-summary', () => props.year, () => props.month],
  queryFn: async () => {
    const res = (await planApi.customerSummary({ year: props.year, month: props.month })) as any
    return res
  },
  staleTime: 30_000,
})

const customerList = computed(() => summaryData.value?.customers ?? [])
const shippedRate = computed(() => {
  const total = summaryData.value?.total_plan_qty || 0
  const shipped = summaryData.value?.total_shipped_qty || 0
  return total > 0 ? Math.round((shipped / total) * 100) : 0
})

const { data: monthlyData, isLoading: isLoadingMonthly } = useQuery({
  queryKey: ['plan-monthly-stats', () => props.year, () => props.month, selectedCustomerId],
  queryFn: async () => {
    const params: Record<string, any> = { year: props.year, month: props.month }
    if (selectedCustomerId.value) params.customer_id = Number(selectedCustomerId.value)
    return (await planApi.monthly(params)) as any
  },
  staleTime: 30_000,
})

const customerFilterOptions = computed(() => {
  const customers = monthlyData.value?.customers ?? []
  const options: { value: string; label: string }[] = [{ value: '', label: '全部客户' }]
  for (const c of customers) {
    if (c.id && c.name) options.push({ value: String(c.id), label: c.name })
  }
  return options
})

const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六']

const dateRows = computed(() => {
  const plansByDate = monthlyData.value?.plans_by_date ?? {}
  const dates = Object.keys(plansByDate).sort()
  if (dates.length === 0) return []

  let cumPlanQty = 0
  let cumShippedQty = 0

  return dates.map((dateStr) => {
    const items = plansByDate[dateStr] || []
    let dayPlanQty = 0
    let dayShippedQty = 0

    for (const item of items) {
      dayPlanQty += Number(item.quantity || item.plan_qty || 0)
      dayShippedQty += Number(item.shipped_qty || 0)
    }

    cumPlanQty += dayPlanQty
    cumShippedQty += dayShippedQty

    const d = new Date(dateStr)
    const weekday = WEEKDAYS[d.getDay()]

    return {
      date: dateStr,
      weekday: `周${weekday}`,
      dayPlanQty,
      cumPlanQty,
      dayShippedQty,
      cumShippedQty,
      cumRemaining: cumPlanQty - cumShippedQty,
    }
  })
})
</script>

<style scoped>
.stat-tab {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.stat-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}
@media (max-width: 768px) {
  .stat-cards {
    grid-template-columns: repeat(2, 1fr);
  }
}
.stat-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  gap: 12px;
  flex-wrap: wrap;
}
.stat-card-title {
  font-weight: 600;
}
.stat-record-count {
  color: var(--color-text-secondary);
  font-size: 0.85rem;
}
.stat-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px 0;
}

.stat-table-wrap {
  overflow-x: auto;
}
.stat-table {
  width: 100%;
  border-collapse: collapse;
}
.stat-table th,
.stat-table td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--color-border-light);
  font-size: 0.85rem;
}
.stat-table thead th {
  background: var(--color-surface);
  font-weight: 600;
  white-space: nowrap;
  font-size: 0.78rem;
  letter-spacing: 0.05em;
  color: var(--color-text-secondary);
}
.stat-table tbody tr:hover {
  background: rgba(91, 141, 239, 0.04);
}

.stat-th-num { text-align: right; }
.stat-th-center { text-align: center; }
.stat-td-num { text-align: right; }
.stat-td-center { text-align: center; }
.stat-td-customer { font-weight: 600; }

.stat-fw-semibold { font-weight: 600; }
.stat-text-success { color: var(--color-success-500); }
.stat-text-danger { color: var(--color-danger-500); font-weight: 600; }
.stat-text-muted { color: var(--color-text-muted); }

.stat-date-cell {
  font-weight: 600;
  font-size: 0.85rem;
}
.stat-weekday {
  margin-left: 6px;
  color: var(--color-text-muted);
  font-size: 0.8rem;
}

.stat-rate-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}
.stat-rate-bar {
  flex: 1;
  height: 6px;
  border-radius: 3px;
  background: var(--color-border-light);
  overflow: hidden;
}
.stat-rate-fill {
  height: 100%;
  border-radius: 3px;
  background: var(--gradient-primary);
  transition: width 0.4s;
}
.stat-rate-done {
  background: var(--gradient-success);
}
.stat-rate-text {
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--color-text-secondary);
  min-width: 32px;
  text-align: right;
}
</style>
