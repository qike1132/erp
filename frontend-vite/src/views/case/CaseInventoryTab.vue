<template>
  <div class="ci-wrap">
    <!-- 库存汇总 -->
    <div class="ci-section">
      <div class="ci-section-header">
        <div class="ci-section-title">
          <i class="fas fa-warehouse" style="color: var(--color-primary-500)" />
          皮套库存汇总
        </div>
        <div class="ci-header-actions">
          <div class="ci-search-wrapper">
            <i class="fas fa-search ci-search-icon" />
            <input v-model="invSearch" class="ci-search-input" placeholder="搜索产品名称或69码..." />
          </div>
          <button class="ci-action-btn ci-action-primary" @click="invRefetch()">
            <i class="fas fa-sync-alt" style="margin-right: 4px" />刷新
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
      <div v-if="invIsLoading" class="ci-loading"><i class="fas fa-spinner fa-spin" /><span>加载中...</span></div>
      <div v-else-if="filteredInventory.length === 0" class="ci-empty"><i class="fas fa-warehouse" /><span>暂无库存数据</span></div>
      <table v-else class="ci-table">
        <thead>
          <tr>
            <th style="text-align: left">产品名称</th>
            <th>69码</th>
            <th style="text-align: right">初始库存</th>
            <th style="text-align: right">累计入库</th>
            <th style="text-align: right">累计出库</th>
            <th style="text-align: right">当前库存</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in filteredInventory" :key="row.name" style="cursor: pointer" @click="selectCaseRow(row)">
            <td style="text-align: left"><strong>{{ row.name }}</strong></td>
            <td><small>{{ row.barcode || '-' }}</small></td>
            <td style="text-align: right">{{ row.initial_stock }}</td>
            <td style="text-align: right"><span style="color: var(--color-success-500)">{{ row.total_in }}</span></td>
            <td style="text-align: right"><span style="color: var(--color-danger-500)">{{ row.total_out }}</span></td>
            <td style="text-align: right">
              <strong :style="{ color: row.current_stock < 0 ? 'var(--color-danger-500)' : 'var(--color-primary-500)' }">{{ row.current_stock }}</strong>
            </td>
            <td>
              <button class="ci-icon-btn ci-icon-info" @click.stop="selectCaseRow(row)">
                <i class="fas fa-history" style="margin-right: 2px" />流水
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 库存流水记录 -->
    <div v-if="selectedCaseName" class="ci-section">
      <div class="ci-section-header">
        <div class="ci-section-title">
          <i class="fas fa-history" style="color: var(--color-primary-500)" />
          库存流水记录 <small style="color: var(--color-text-muted)">- {{ selectedCaseName }}</small>
        </div>
        <button class="ci-action-btn ci-action-outline" @click="showLogFilter = !showLogFilter">
          <i class="fas fa-filter" style="margin-right: 4px" />筛选
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
              <i class="fas fa-search" style="margin-right: 4px" />查询
            </button>
            <button class="ci-action-btn ci-action-outline" style="margin-left: 8px" @click="clearLogFilter">
              <i class="fas fa-times" />
            </button>
          </div>
        </div>
      </div>
      <div v-if="logIsLoading" class="ci-loading"><i class="fas fa-spinner fa-spin" /><span>加载中...</span></div>
      <div v-else-if="logList.length === 0" class="ci-empty"><i class="fas fa-history" /><span>暂无流水记录</span></div>
      <table v-else class="ci-table">
        <thead>
          <tr>
            <th>操作类型</th>
            <th style="text-align: right">变化数量</th>
            <th>客户</th>
            <th>关联单号</th>
            <th>时间</th>
            <th>备注</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in logList" :key="row.id">
            <td>
              <span :class="['ci-badge', logBadgeClass(row.change_type)]">{{ row.change_type }}</span>
            </td>
            <td style="text-align: right">
              <strong :style="{ color: row.change_quantity >= 0 ? 'var(--color-success-500)' : 'var(--color-danger-500)' }">
                {{ row.change_quantity >= 0 ? '+' : '' }}{{ row.change_quantity }}
              </strong>
            </td>
            <td>{{ row.customer || '-' }}</td>
            <td>{{ row.related_id || '-' }}</td>
            <td><small>{{ row.change_date }}</small></td>
            <td><small>{{ row.note || '-' }}</small></td>
          </tr>
        </tbody>
      </table>
      <UiPagination v-if="logTotalPages > 1" :current-page="logPage" :total-pages="logTotalPages" @update:current-page="logPage = $event; logRefetch()" />
    </div>

    <!-- 未选中提示 -->
    <div v-if="!selectedCaseName" class="ci-section">
      <div class="ci-empty-hint">
        <i class="fas fa-info-circle" />
        <p>请点击上方库存表格中的产品查看流水记录</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { get } from '@/api/request'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import UiPagination from '@/components/ui/UiPagination.vue'

const queryClient = useQueryClient()

// === 库存汇总 ===
const invSearch = ref('')
const selectedCaseId = ref<number | null>(null)
const selectedCaseName = ref('')

const {
  data: invData,
  isLoading: invIsLoading,
  refetch: invRefetch,
} = useQuery({
  queryKey: ['case-inventory'],
  queryFn: () => get('/cases/inventory-summary') as Promise<any>,
  staleTime: 30_000,
})

const inventoryList = computed(() => {
  const list: any[] = invData.value?.inventory ?? invData.value ?? []
  return list
})

const filteredInventory = computed(() => {
  if (!invSearch.value) return inventoryList.value
  const q = invSearch.value.toLowerCase()
  return inventoryList.value.filter(
    (i: any) => i.name?.toLowerCase().includes(q) || i.barcode?.toLowerCase().includes(q),
  )
})

const invTotalStock = computed(() =>
  filteredInventory.value.reduce((s: number, i: any) => s + (i.current_stock || 0), 0),
)
const invTotalIn = computed(() => filteredInventory.value.reduce((s: number, i: any) => s + (i.total_in || 0), 0))
const invTotalOut = computed(() => filteredInventory.value.reduce((s: number, i: any) => s + (i.total_out || 0), 0))

function selectCaseRow(row: any) {
  selectedCaseId.value = row.id
  selectedCaseName.value = row.name
  logPage.value = 1
}

// === 库存流水 ===
const showLogFilter = ref(false)
const logFilterType = ref('')
const logFilterStart = ref('')
const logFilterEnd = ref('')
const logPage = ref(1)
const logTotalPages = ref(1)

const logTypeOptions = [
  { value: '入库', label: '入库' },
  { value: '出库', label: '出库' },
  { value: '入库调整', label: '入库调整' },
  { value: '出库调整', label: '出库调整' },
  { value: '删除入库', label: '删除入库' },
  { value: '删除出库', label: '删除出库' },
]

const {
  data: logData,
  isLoading: logIsLoading,
  refetch: logRefetch,
} = useQuery({
  queryKey: ['case-inventory-logs', selectedCaseId, logPage, logFilterType, logFilterStart, logFilterEnd],
  queryFn: async () => {
    const params: Record<string, any> = { page: logPage.value, per_page: 10 }
    if (logFilterType.value) params.type = logFilterType.value
    if (logFilterStart.value) params.start_date = logFilterStart.value
    if (logFilterEnd.value) params.end_date = logFilterEnd.value
    const res = (await get(`/cases/inventory-logs/${selectedCaseId.value}`, params)) as any
    logTotalPages.value = res.pagination?.pages ?? 1
    return res
  },
  enabled: computed(() => !!selectedCaseId.value),
  staleTime: 30_000,
})

const logList = computed(() => logData.value?.logs ?? logData.value?.items ?? [])

function clearLogFilter() {
  logFilterType.value = ''
  logFilterStart.value = ''
  logFilterEnd.value = ''
  logPage.value = 1
}

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
  transition: all 0.3s ease;
  font-family: inherit;
  color: var(--color-text);
}
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
  transition: all 0.3s ease;
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
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}
.ci-stat-card:hover {
  box-shadow: 0 12px 36px rgba(0,0,0,0.08), 0 48px 144px rgba(0,0,0,0.12);
  transform: translateY(-6px);
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

/* Table */
.ci-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.ci-table thead th {
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
.ci-table tbody td {
  padding: 10px 14px;
  font-size: 13px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  text-align: center;
  vertical-align: middle;
  transition: background 0.2s ease;
  color: var(--color-text);
}
.ci-table tbody tr:hover { background: var(--color-primary-50); }

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
  transition: all 0.2s ease;
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
