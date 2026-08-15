<template>
  <div class="ci-wrap">
    <!-- 库存汇总 -->
    <div class="ci-section">
      <div class="ci-section-header">
        <div class="ci-section-title">
          <FontAwesomeIcon icon="warehouse" style="color: var(--color-primary-500)"  aria-hidden="true" />
          皮套库存汇总
        </div>
        <div class="ci-header-actions">
          <UiSearchInput v-model="invSearch" placeholder="搜索产品名称或69码..." @search="onInvSearchInput" />
          <button class="ci-action-btn ci-action-primary" @click="invRefetch()">
            <FontAwesomeIcon icon="sync-alt" style="margin-right: 4px"  aria-hidden="true" />刷新
          </button>
        </div>
      </div>

      <!-- 统计卡片 -->
      <div class="ci-stat-row">
        <div class="ci-stat-card ci-stat-success">
          <div class="ci-stat-value">{{ invTotalStock }}</div>
          <div class="ci-stat-label">当前总库存</div>
        </div>
        <div class="ci-stat-card ci-stat-primary">
          <div class="ci-stat-value">{{ invTotalIn }}</div>
          <div class="ci-stat-label">累计入库</div>
        </div>
        <div class="ci-stat-card ci-stat-danger">
          <div class="ci-stat-value">{{ invTotalOut }}</div>
          <div class="ci-stat-label">累计出库</div>
        </div>
      </div>

      <!-- 库存表格 -->
      <div v-if="invIsFetching" class="ci-fetching-bar"><div class="ci-fetching-progress" /></div>
      <UiDataTable
        :data="inventoryList"
        :columns="inventoryColumns"
        :loading="invIsLoading && inventoryList.length === 0"
        :paginator="invTotalPages > 1"
        :rows="invPerPage"
        :total-records="invTotalPages * invPerPage"
        row-key="id"
        @page="onInvPageChange"
        @rowClick="(row: any) => selectCaseRow(row)"
      >
        <template #empty>
          <div class="ci-empty"><FontAwesomeIcon icon="warehouse" aria-hidden="true" /><span>暂无库存数据</span></div>
        </template>
        <template #column-body-name="{ row }"><strong>{{ (row as InventorySummaryItem).name }}</strong></template>
        <template #column-body-barcode="{ row }"><small>{{ (row as InventorySummaryItem).barcode || '-' }}</small></template>
        <template #column-body-total_in="{ row }"><span style="color: var(--color-success-500)">{{ (row as InventorySummaryItem).total_in }}</span></template>
        <template #column-body-total_out="{ row }"><span style="color: var(--color-danger-500)">{{ (row as InventorySummaryItem).total_out }}</span></template>
        <template #column-body-current_stock="{ row }">
          <strong :style="{ color: (row as InventorySummaryItem).current_stock < 0 ? 'var(--color-danger-500)' : 'var(--color-primary-500)' }">{{ (row as InventorySummaryItem).current_stock }}</strong>
        </template>
        <template #column-body-actions="{ row }">
          <button class="ci-icon-btn ci-icon-info" @click.stop="selectCaseRow(row as InventorySummaryItem)">
            <FontAwesomeIcon icon="history" style="margin-right: 2px" aria-hidden="true" />流水
          </button>
        </template>
      </UiDataTable>
    </div>

    <!-- 库存流水记录 -->
    <div v-if="selectedCaseName" class="ci-section">
      <div class="ci-section-header">
        <div class="ci-section-title">
          <FontAwesomeIcon icon="history" style="color: var(--color-primary-500)"  aria-hidden="true" />
          库存流水记录 <small style="color: var(--color-text-muted)">- {{ selectedCaseName }}</small>
        </div>
        <button class="ci-action-btn ci-action-outline" @click="showLogFilter = !showLogFilter">
          <FontAwesomeIcon icon="filter" style="margin-right: 4px"  aria-hidden="true" />筛选
        </button>
      </div>
      <div v-if="showLogFilter" class="ci-filter-panel">
        <div class="ci-filter-row">
          <div class="ci-filter-field">
            <label class="ci-form-label">操作类型</label>
            <UiSelect v-model="logFilterType" placeholder="全部" :options="logTypeOptions" style="width: 140px" />
          </div>
          <div class="ci-filter-field">
            <label class="ci-form-label">开始日期</label>
            <UiDatePicker v-model="logFilterStart" style="width: 100%" />
          </div>
          <div class="ci-filter-field">
            <label class="ci-form-label">结束日期</label>
            <UiDatePicker v-model="logFilterEnd" style="width: 100%" />
          </div>
          <div class="ci-filter-action">
            <button class="ci-action-btn ci-action-primary" @click="logPage = 1; logRefetch()">
              <FontAwesomeIcon icon="search" style="margin-right: 4px"  aria-hidden="true" />查询
            </button>
            <button class="ci-action-btn ci-action-outline" style="margin-left: 8px" @click="clearLogFilter" aria-label="关闭">
              <FontAwesomeIcon icon="times" aria-hidden="true" />
            </button>
          </div>
        </div>
      </div>
      <div v-if="logIsLoading && logList.length === 0" class="ci-loading"><UiSpinner /></div>
      <template v-else>
      <div v-if="logIsFetching" class="ci-fetching-bar"><div class="ci-fetching-progress" /></div>
      <UiDataTable
        :data="logList"
        :columns="logColumns"
        :loading="logIsLoading"
        :paginator="logTotalPages > 1"
        :rows="logPerPage"
        :total-records="logTotalPages * logPerPage"
        row-key="id"
        @page="onLogPageChange"
      >
        <template #empty><div class="ci-empty"><FontAwesomeIcon icon="history" aria-hidden="true" /><span>暂无流水记录</span></div></template>
        <template #column-body-change_type="{ row }">
          <span :class="['ci-badge', logBadgeClass((row as InventoryLogItem).change_type)]">{{ (row as InventoryLogItem).change_type }}</span>
        </template>
        <template #column-body-change_quantity="{ row }">
          <strong :style="{ color: (row as InventoryLogItem).change_quantity >= 0 ? 'var(--color-success-500)' : 'var(--color-danger-500)' }">
            {{ (row as InventoryLogItem).change_quantity >= 0 ? '+' : '' }}{{ (row as InventoryLogItem).change_quantity }}
          </strong>
        </template>
        <template #column-body-customer="{ row }">{{ (row as InventoryLogItem).customer || '-' }}</template>
        <template #column-body-related_id="{ row }">{{ (row as InventoryLogItem).related_id || '-' }}</template>
        <template #column-body-change_date="{ row }"><small>{{ (row as InventoryLogItem).change_date }}</small></template>
        <template #column-body-note="{ row }"><small>{{ (row as InventoryLogItem).note || '-' }}</small></template>
      </UiDataTable>
      </template>
    </div>

    <!-- 未选中提示 -->
    <div v-if="!selectedCaseName" class="ci-section">
      <div class="ci-empty-hint">
        <FontAwesomeIcon icon="info-circle" aria-hidden="true" />
        <p>请点击上方库存表格中的产品查看流水记录</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * CaseInventoryTab.vue — 皮套库存查询标签页
 *
 * 职责：
 * - 展示皮套库存汇总（统计卡片 + 分页表格）
 * - 点击产品行查看该产品的库存流水记录
 * - 支持按操作类型、日期范围筛选流水
 */
import { ref, computed } from 'vue'
import { useQuery, keepPreviousData } from '@tanstack/vue-query'
import { get } from '@/api/request'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
import { useDebouncedSearch } from '@/composables/useDebouncedSearch'

/** 库存汇总中单个产品的库存信息 */
interface InventorySummaryItem {
  id: number
  name: string
  barcode?: string
  initial_stock: number
  total_in: number
  total_out: number
  current_stock: number
}

/** 库存汇总响应 */
interface InventorySummaryResponse {
  inventory: InventorySummaryItem[]
  pages: number
  stats: {
    total_stock: number
    total_in: number
    total_out: number
  }
}

/** 库存流水中单条记录 */
interface InventoryLogItem {
  id: number
  change_type: string
  change_quantity: number
  customer?: string
  related_id?: string
  change_date: string
  note?: string
}

/** 库存流水响应 */
interface InventoryLogResponse {
  logs: InventoryLogItem[]
  pagination: {
    pages: number
  }
}

// ===== 库存汇总 =====
/** 搜索关键词（即时绑定输入框） */
const invSearch = ref('')
/** 防抖后的搜索关键词 */
const debouncedInvSearch = ref('')
/** 当前页码 */
const invPage = ref(1)
/** 每页条数（可由分页器选择） */
const invPerPage = ref(50)
/** 当前选中的产品 ID */
const selectedCaseId = ref<number | null>(null)
/** 当前选中的产品名称（用于流水标题显示） */
const selectedCaseName = ref('')

const { debounceSearch: debounceInvSearch } = useDebouncedSearch()

/** 搜索输入防抖处理（300ms） */
function onInvSearchInput() {
  debounceInvSearch(() => {
    debouncedInvSearch.value = invSearch.value
    invPage.value = 1
  })
}

/** 库存汇总查询（服务端分页 + 搜索） */
const {
  data: invData,
  isLoading: invIsLoading,
  isFetching: invIsFetching,
  refetch: invRefetch,
} = useQuery({
  queryKey: ['case-inventory', invPage, debouncedInvSearch, invPerPage],
  queryFn: () => get<InventorySummaryResponse>('/cases/inventory-summary', { page: invPage.value, per_page: invPerPage.value, search: debouncedInvSearch.value }),
  staleTime: 30_000,
  gcTime: 60_000,
  placeholderData: keepPreviousData,
})

/** 库存列表 */
const inventoryList = computed<InventorySummaryItem[]>(() => invData.value?.inventory ?? [])
/** 库存总页数 */
const invTotalPages = computed(() => invData.value?.pages ?? 0)
/** 库存统计数据 */
const invStats = computed(() => invData.value?.stats ?? null)

/** 当前总库存 */
const invTotalStock = computed(() => invStats.value?.total_stock ?? 0)
/** 累计入库 */
const invTotalIn = computed(() => invStats.value?.total_in ?? 0)
/** 累计出库 */
const invTotalOut = computed(() => invStats.value?.total_out ?? 0)

/** 选中产品行，加载该产品的流水记录 */
function selectCaseRow(row: InventorySummaryItem) {
  selectedCaseId.value = row.id
  selectedCaseName.value = row.name
  logPage.value = 1
}

// ===== 库存流水 =====
/** 是否显示流水筛选面板 */
const showLogFilter = ref(false)
/** 流水筛选：操作类型 */
const logFilterType = ref('')
/** 流水筛选：开始日期 */
const logFilterStart = ref('')
/** 流水筛选：结束日期 */
const logFilterEnd = ref('')
/** 流水当前页码 */
const logPage = ref(1)
/** 流水每页条数（可由分页器选择） */
const logPerPage = ref(10)
/** 流水总页数（由 queryFn 更新） */
const logTotalPages = ref(1)

/** 操作类型选项 */
const logTypeOptions = [
  { value: '入库', label: '入库' },
  { value: '出库', label: '出库' },
  { value: '入库调整', label: '入库调整' },
  { value: '出库调整', label: '出库调整' },
  { value: '删除入库', label: '删除入库' },
  { value: '删除出库', label: '删除出库' },
]

/** 库存流水查询（依赖选中的产品 ID） */
const {
  data: logData,
  isLoading: logIsLoading,
  isFetching: logIsFetching,
  refetch: logRefetch,
} = useQuery({
  queryKey: ['case-inventory-logs', selectedCaseId, logPage, logFilterType, logFilterStart, logFilterEnd, logPerPage],
  queryFn: async () => {
    const params: Record<string, string | number> = { page: logPage.value, per_page: logPerPage.value }
    if (logFilterType.value) params.type = logFilterType.value
    if (logFilterStart.value) params.start_date = logFilterStart.value
    if (logFilterEnd.value) params.end_date = logFilterEnd.value
    const res = await get<InventoryLogResponse>(`/cases/inventory-logs/${selectedCaseId.value}`, params)
    logTotalPages.value = res.pagination?.pages ?? 1
    return res
  },
  enabled: computed(() => !!selectedCaseId.value),
  staleTime: 30_000,
  placeholderData: keepPreviousData,
})

/** 流水记录列表 */
const logList = computed<InventoryLogItem[]>(() => logData.value?.logs ?? [])

/** UiDataTable 列定义 */
const inventoryColumns: TableColumn[] = [
  { field: 'name', header: '产品名称', align: 'left' },
  { field: 'barcode', header: '69码', align: 'center' },
  { field: 'initial_stock', header: '初始库存', align: 'right' },
  { field: 'total_in', header: '累计入库', align: 'right' },
  { field: 'total_out', header: '累计出库', align: 'right' },
  { field: 'current_stock', header: '当前库存', align: 'right' },
  { field: 'actions', header: '操作', align: 'center' },
]
const logColumns: TableColumn[] = [
  { field: 'change_type', header: '操作类型', align: 'center' },
  { field: 'change_quantity', header: '变化数量', align: 'right' },
  { field: 'customer', header: '客户', align: 'center' },
  { field: 'related_id', header: '关联单号', align: 'center' },
  { field: 'change_date', header: '时间', align: 'center' },
  { field: 'note', header: '备注', align: 'center' },
]

/** UiDataTable 分页变化处理（PrimeVue page 为 0 索引） */
function onInvPageChange(event: { page: number; rows: number }) {
  invPage.value = event.page + 1
  invPerPage.value = event.rows
}
function onLogPageChange(event: { page: number; rows: number }) {
  logPage.value = event.page + 1
  logPerPage.value = event.rows
}

/** 清空流水筛选条件 */
function clearLogFilter() {
  logFilterType.value = ''
  logFilterStart.value = ''
  logFilterEnd.value = ''
  logPage.value = 1
}

/** 根据操作类型返回对应的徽章 CSS 类名 */
function logBadgeClass(t: string): string {
  const map: Record<string, string> = {
    '入库': 'ci-badge-success',
    '出库': 'ci-badge-danger',
    '入库调整': 'ci-badge-warning',
    '出库调整': 'ci-badge-warning',
    '删除入库': 'ci-badge-info',
    '删除出库': 'ci-badge-info',
    '批量导入入库': 'ci-badge-success',
    '批量导入出库': 'ci-badge-danger',
  }
  return map[t] ?? 'ci-badge-info'
}
</script>

<style scoped>
.ci-wrap {
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* Section */
.ci-section {
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 13px;
  overflow: hidden;
  background: white;
}

/* Section header */
.ci-section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
}
.ci-section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
}
.ci-section-title i {
  font-size: 14px;
}
.ci-header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

/* Search */
.ci-search-wrapper {
  position: relative;
  width: 200px;
}
.ci-search-icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-text-muted);
  font-size: 12px;
}
.ci-search-input {
  width: 100%;
  padding: 8px 12px 8px 32px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  background: white;
  font-size: 13px;
  outline: none;
  transition: border-color 0.3s ease, background 0.3s ease, box-shadow 0.3s ease;
  font-family: inherit;
  color: var(--color-text);
}
.ci-search-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.ci-search-input:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}

/* Action buttons */
.ci-action-btn {
  padding: 6px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  background: white;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.3s ease, border-color 0.3s ease, transform 0.3s ease;
  color: var(--color-text-secondary);
}
.ci-action-primary { color: var(--color-primary-600); }
.ci-action-primary:hover:not(:disabled) { background: var(--color-primary-50); border-color: var(--color-primary-300); transform: translateY(-1px); }
.ci-action-outline { }
.ci-action-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* Stat cards */
.ci-stat-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  padding: 16px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
}
.ci-stat-card {
  border-radius: 13px;
  padding: 16px;
  text-align: center;
  border: 1px solid transparent;
  transition: box-shadow 0.4s cubic-bezier(0.4, 0, 0.2, 1), transform 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}
.ci-stat-card:hover {
  box-shadow: 0 4px 12px rgba(0,0,0,0.06);
  transform: translateY(-2px);
}
.ci-stat-value {
  font-size: 28px;
  font-weight: 800;
  margin-bottom: 4px;
  font-variant-numeric: tabular-nums;
}
.ci-stat-label {
  font-size: 12px;
  color: var(--color-text-secondary);
}
.ci-stat-success { background: var(--color-success-50); border-color: var(--color-success-200); }
.ci-stat-success .ci-stat-value { color: var(--color-success-600); }
.ci-stat-primary { background: var(--color-primary-50); border-color: var(--color-primary-200); }
.ci-stat-primary .ci-stat-value { color: var(--color-primary-600); }
.ci-stat-danger { background: var(--color-danger-50); border-color: var(--color-danger-200); }
.ci-stat-danger .ci-stat-value { color: var(--color-danger-600); }

/* Badge */
.ci-badge {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 16px;
  font-size: 12px;
  font-weight: 600;
}
.ci-badge-success { background: var(--color-success-50); color: var(--color-success-600); }
.ci-badge-danger { background: var(--color-danger-50); color: var(--color-danger-600); }
.ci-badge-warning { background: var(--color-warning-50); color: var(--color-warning-600); }
.ci-badge-info { background: var(--color-info-50); color: var(--color-info-600); }

/* Icon button */
.ci-icon-btn {
  border: none;
  border-radius: 7px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 12px;
  transition: background 0.2s ease;
  padding: 4px 8px;
  gap: 4px;
}
.ci-icon-info { background: var(--color-info-50); color: var(--color-info-700); }
.ci-icon-info:hover { background: var(--color-info-100); }

/* Filter */
.ci-filter-panel {
  border-bottom: 1px solid var(--color-border-light);
  padding: 12px 16px;
}
.ci-filter-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: flex-end;
}
.ci-filter-field { flex: 0 0 auto; }
.ci-filter-action { display: flex; align-items: flex-end; }
.ci-form-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--color-text-secondary);
  margin-bottom: 6px;
}

/* Loading & Empty */
.ci-loading, .ci-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 32px 0;
  color: var(--color-text-muted);
}
.ci-empty {
  flex-direction: column;
}
.ci-empty i { font-size: 28px; opacity: 0.5; }

/* Fetching progress bar */
.ci-fetching-bar {
  height: 2px;
  background: var(--color-primary-100, #e0f2fe);
  overflow: hidden;
  border-radius: 1px;
}
.ci-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500, #3b82f6);
  border-radius: 1px;
  animation: ci-progress-slide 1s ease-in-out infinite;
}
@keyframes ci-progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}

/* Empty hint */
.ci-empty-hint {
  text-align: center;
  color: var(--color-text-muted);
  padding: 32px 0;
}
.ci-empty-hint i {
  font-size: 28px;
  opacity: 0.3;
  display: block;
  margin-bottom: 8px;
}
</style>
