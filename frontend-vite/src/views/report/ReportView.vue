<template>
  <div class="rp-container">
    <div class="rp-card rp-card-main">
      <!-- 卡片头部 -->
      <div class="rp-card-header">
        <div class="rp-header-left">
          <HeaderTabs />
        </div>
        <div class="rp-header-right">
          <div class="rp-tab-group">
            <button v-for="tab in tabs" :key="tab.value" :class="['rp-tab-btn', { active: activeTab === tab.value }]" @click="activeTab = tab.value; handleTabChange()">
              {{ tab.label }}
            </button>
          </div>
        </div>
      </div>

      <!-- 筛选栏 -->
      <div class="rp-filter-bar">
        <div class="rp-filter-field">
          <label class="rp-filter-label">客户名称</label>
          <UiSelect v-model="filters.customer" placeholder="全部客户" style="width: 160px" :options="customerOptions" />
        </div>
        <div class="rp-filter-field">
          <label class="rp-filter-label">产品名称/SKU</label>
          <input v-model="filters.product" class="rp-filter-input" placeholder="输入产品名称或SKU" />
        </div>
        <div class="rp-filter-field">
          <label class="rp-filter-label">开始日期</label>
          <UiDatePicker v-model="filters.startDate" style="width: 160px" />
        </div>
        <div class="rp-filter-field">
          <label class="rp-filter-label">结束日期</label>
          <UiDatePicker v-model="filters.endDate" style="width: 160px" />
        </div>
        <div class="rp-filter-actions">
          <button class="rp-action-btn rp-action-primary" @click="doSearch">查询</button>
          <button class="rp-action-btn rp-action-outline" @click="doReset">重置</button>
          <button v-if="searched" class="rp-action-btn rp-action-success" @click="exportReport">
            <i class="fas fa-download" style="margin-right: 4px" />导出
          </button>
        </div>
      </div>

      <!-- 表格 -->
      <div class="rp-table-wrap">
        <div v-if="isLoading && searched && !logs.length" class="rp-empty">
          <i class="fas fa-spinner fa-spin" />
          <span>加载中...</span>
        </div>
        <div v-else-if="!logs.length" class="rp-empty">
          <i class="fas fa-chart-line" />
          <span>{{ isFetching ? '加载中...' : '暂无数据' }}</span>
        </div>
        <template v-else>
        <div v-if="isFetching" class="rp-fetching-bar"><div class="rp-fetching-progress" /></div>
        <table class="rp-table">
          <thead>
            <tr>
              <th>{{ currentCfg.dateLabel }}</th>
              <th>客户</th>
              <th style="text-align: left">产品名称</th>
              <th>{{ currentCfg.countLabel }}</th>
              <th style="text-align: left">{{ activeTab === 'deduction' ? '订单备注' : '备注' }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, idx) in logs" :key="row.id ?? idx">
              <td>{{ row[currentCfg.dateKey] || '-' }}</td>
              <td>{{ row.customer || '-' }}</td>
              <td style="text-align: left">{{ row.product_name || '-' }}</td>
              <td>{{ row.quantity }}</td>
              <td style="text-align: left"><span :title="row[currentCfg.noteKey]">{{ row[currentCfg.noteKey] || '-' }}</span></td>
            </tr>
          </tbody>
        </table>

        <!-- 分页 -->
        <UiPagination v-if="pagination && pagination.pages > 1" :current-page="page" :total-pages="pagination.pages" :total-items="pagination.total" @update:current-page="handlePageChange" />
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { useQuery, keepPreviousData } from '@tanstack/vue-query'
import { reportApi, customerApi } from '@/api'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import HeaderTabs from '@/layouts/components/HeaderTabs.vue'

type TabType = 'order' | 'stockin' | 'stockout' | 'deduction'

interface TabConfig {
  label: string
  endpoint: string
  dateKey: string
  countKey: string
  dateLabel: string
  countLabel: string
  noteKey: string
}

const TAB_CONFIG: Record<TabType, TabConfig> = {
  order: {
    label: '订单流水',
    endpoint: '/reports/order-logs',
    dateKey: 'order_date',
    countKey: 'order_count',
    dateLabel: '下单时间',
    countLabel: '数量',
    noteKey: 'note',
  },
  stockin: {
    label: '备货流水',
    endpoint: '/reports/stockin-logs',
    dateKey: 'stockin_date',
    countKey: 'stockin_count',
    dateLabel: '备货时间',
    countLabel: '备货数量',
    noteKey: 'note',
  },
  stockout: {
    label: '出货流水',
    endpoint: '/reports/stockout-logs',
    dateKey: 'stockout_date',
    countKey: 'stockout_count',
    dateLabel: '出货时间',
    countLabel: '出货数量',
    noteKey: 'note',
  },
  deduction: {
    label: '备货抵扣流水',
    endpoint: '/reports/deduction-logs',
    dateKey: 'deduction_time',
    countKey: 'deduction_count',
    dateLabel: '抵扣时间',
    countLabel: '抵扣数量',
    noteKey: 'order_note',
  },
}

const tabs: { value: TabType; label: string }[] = [
  { value: 'order', label: '订单流水' },
  { value: 'stockin', label: '备货流水' },
  { value: 'stockout', label: '出货流水' },
  { value: 'deduction', label: '备货抵扣流水' },
]

const activeTab = ref<TabType>('order')
const page = ref(1)
const searched = ref(true)

const filters = reactive({ customer: '', product: '', startDate: '', endDate: '' })

const currentCfg = computed(() => TAB_CONFIG[activeTab.value])

// 客户名称列表
const { data: namesData } = useQuery({
  queryKey: ['customer-active-names'],
  queryFn: () => customerApi.activeNames() as Promise<any>,
  staleTime: 30_000,
})
const customerNames = computed(() => namesData.value?.names ?? namesData.value ?? [])
const customerOptions = computed(() =>
  customerNames.value.map((c: any) => ({ value: c.name ?? c, label: c.name ?? c })),
)

// 报表数据
const { data: reportData, isLoading, isFetching } = useQuery({
  queryKey: ['report-data', activeTab, page, filters],
  queryFn: async () => {
    const params: Record<string, any> = { page: page.value, per_page: 15 }
    if (filters.customer) params.customer = filters.customer
    if (filters.product) params.product = filters.product
    if (filters.startDate) params.start_date = filters.startDate
    if (filters.endDate) params.end_date = filters.endDate
    const res = (await reportApi[currentTabEndpoint()](params)) as any
    return res
  },
  enabled: searched,
  staleTime: 30_000,
  placeholderData: keepPreviousData,
})

function currentTabEndpoint(): keyof typeof reportApi {
  const map: Record<TabType, keyof typeof reportApi> = {
    order: 'orderLogs',
    stockin: 'stockinLogs',
    stockout: 'stockoutLogs',
    deduction: 'deductionLogs',
  }
  return map[activeTab.value]
}

const logs = computed(() => reportData.value?.logs ?? [])
const pagination = computed(() => reportData.value?.pagination)

function doSearch() {
  searched.value = true
  page.value = 1
}
function doReset() {
  Object.assign(filters, { customer: '', product: '', startDate: '', endDate: '' })
  page.value = 1
}
function handleTabChange() {
  page.value = 1
}
function handlePageChange(p: number) {
  page.value = p
}

function exportReport() {
  const params = new URLSearchParams()
  params.set('report_type', activeTab.value)
  if (filters.customer) params.set('customer', filters.customer)
  if (filters.product) params.set('product', filters.product)
  if (filters.startDate) params.set('start_date', filters.startDate)
  if (filters.endDate) params.set('end_date', filters.endDate)
  window.open(`/api/v1/reports/export?${params.toString()}`, '_blank')
}
</script>

<style scoped>
/* Container */
.rp-container {
  padding: 8px;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* Card */
.rp-card {
  background: white;
  border-radius: 18px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
}
.rp-card:hover {
  box-shadow: 0 12px 36px rgba(0,0,0,0.08), 0 48px 144px rgba(0,0,0,0.12);
  transform: translateY(-6px);
}
.rp-card-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

/* Card Header */
.rp-card-header {
  display: flex;
  flex-wrap: nowrap;
  justify-content: space-between;
  align-items: flex-start;
  padding: 10px 24px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  gap: 12px;
}
.rp-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
}
.rp-header-right {
  display: flex;
  align-items: flex-start;
  justify-content: flex-end;
  gap: 8px;
}
.rp-card-header :deep(.ht-bar) {
  width: auto;
  margin: 0;
}
.rp-card-title-group {
  display: flex;
  align-items: center;
  gap: 12px;
}
.rp-card-title-group h3 {
  font-size: 17px;
  font-weight: 700;
  color: var(--color-text);
  margin: 0;
}
.rp-card-title-group small {
  font-size: 12px;
  color: var(--color-text-secondary);
  display: block;
  margin-top: 2px;
}
.rp-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* Icon Box */
.rp-icon-box {
  width: 46px;
  height: 46px;
  border-radius: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 19px;
  flex-shrink: 0;
}
.rp-icon-orange {
  background: linear-gradient(135deg, var(--color-warning-100), var(--color-warning-200));
  color: var(--color-warning-800);
}

/* Tab Group */
.rp-tab-group {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
}
.rp-tab-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 14px;
  border: none;
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  background: transparent;
  cursor: pointer;
  transition: all 0.3s ease;
}
.rp-tab-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}
.rp-tab-btn.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91, 141, 239, 0.2);
  transform: translateY(-1px);
}

/* Filter Bar */
.rp-filter-bar {
  display: flex;
  gap: 12px;
  padding: 12px 24px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  flex-wrap: wrap;
  align-items: flex-end;
}
.rp-filter-field {
  flex-shrink: 0;
}
.rp-filter-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  margin-bottom: 4px;
}
.rp-filter-input {
  width: 180px;
  padding: 8px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  font-size: 13px;
  outline: none;
  transition: all 0.3s ease;
  font-family: inherit;
  color: var(--color-text);
  background: white;
}
.rp-filter-input:focus {
  border-color: var(--color-primary-400);
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.rp-filter-actions {
  display: flex;
  gap: 8px;
  align-items: flex-end;
}

/* Action Buttons */
.rp-action-btn {
  padding: 7px 14px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  background: white;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
  color: var(--color-text-secondary);
  display: flex;
  align-items: center;
}
.rp-action-primary { color: var(--color-primary-600); }
.rp-action-primary:hover { background: var(--color-primary-50); border-color: var(--color-primary-300); transform: translateY(-1px); }
.rp-action-outline { }
.rp-action-success { color: var(--color-success-600); border-color: var(--color-success-200); }
.rp-action-success:hover { background: var(--color-success-50); border-color: var(--color-success-300); transform: translateY(-1px); }

/* Table */
.rp-table-wrap {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}
.rp-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.rp-table thead th {
  padding: 10px 14px;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  background: var(--color-surface, #f8fafc);
  border-bottom: 2px solid var(--color-border-light, #e2e8f0);
  color: var(--color-text-secondary);
  text-align: center;
}
.rp-table tbody td {
  padding: 10px 14px;
  font-size: 13px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  text-align: center;
  transition: background 0.2s ease;
  color: var(--color-text);
}
.rp-table tbody tr:hover {
  background: var(--color-primary-50);
}

/* Table Footer */


/* Empty */
.rp-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-text-muted);
}
.rp-empty i { font-size: 28px; opacity: 0.5; }
.rp-empty span { font-size: 14px; }

/* Fetching progress bar */
.rp-fetching-bar {
  height: 2px;
  background: var(--color-primary-100, #e0f2fe);
  overflow: hidden;
  border-radius: 1px;
}
.rp-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500, #3b82f6);
  border-radius: 1px;
  animation: rp-progress-slide 1s ease-in-out infinite;
}
@keyframes rp-progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}
</style>
