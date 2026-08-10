<template>
  <div class="cs-stock">
    <!-- 模式切换 -->
    <div class="cs-mode-toggle" role="tablist">
      <button role="tab" :aria-selected="mode === 'stockin'" :class="['cs-mode-btn', { active: mode === 'stockin' }]" @click="switchMode('stockin')">
        <FontAwesomeIcon icon="truck-loading" />入库
      </button>
      <button role="tab" :aria-selected="mode === 'stockout'" :class="['cs-mode-btn', { active: mode === 'stockout', 'out-mode': mode === 'stockout' }]" @click="switchMode('stockout')">
        <FontAwesomeIcon icon="shipping-fast" />出库
      </button>
    </div>

    <!-- 上半部分：录入表单 + 暂存列表 -->
    <div class="cs-top-row">
      <!-- 左：信息录入 -->
      <div class="cs-form-section">
        <div class="cs-section-header">
          <div class="cs-section-title">
            <FontAwesomeIcon :icon="mode === 'stockin' ? 'truck-loading' : 'shipping-fast'" :style="{ color: mode === 'stockin' ? 'var(--color-primary-500)' : 'var(--color-danger-500)' }" aria-hidden="true" />
            {{ mode === 'stockin' ? '入库信息录入' : '出库信息录入' }}
          </div>
          <span v-if="staged.length" :class="['cs-badge', mode === 'stockin' ? 'cs-badge-info' : 'cs-badge-danger']">
            已暂存: {{ staged.length }}
          </span>
        </div>

        <form @submit.prevent class="cs-form">
          <div class="cs-form-row">
            <div class="cs-form-field">
              <label class="cs-form-label">客户名称</label>
              <UiSelect v-model="form.customer" placeholder="请选择客户" :options="customerOptions" />
            </div>
            <div class="cs-form-field">
              <label class="cs-form-label">{{ mode === 'stockin' ? '入库时间' : '出库时间' }}</label>
              <UiDatePicker v-model="form.date" style="width: 100%" />
            </div>
          </div>

          <div class="cs-form-row" style="grid-template-columns: 2fr 1fr">
            <div class="cs-form-field">
              <label class="cs-form-label">产品名称</label>
              <UiAutocomplete
                v-model="form.search"
                :searchFn="searchCaseProducts"
                placeholder="输入产品名称或69码搜索"
                @select="onProductSelect"
              >
                <template #option="{ item }">
                  {{ item.name }}
                  <span v-if="item.barcode" class="cs-barcode-hint">{{ item.barcode }}</span>
                </template>
              </UiAutocomplete>
              <small v-if="mode === 'stockout' && form.productId" class="cs-current-stock">当前库存: {{ currentStock }}</small>
            </div>
            <div class="cs-form-field">
              <label class="cs-form-label">{{ mode === 'stockin' ? '入库数量' : '出库数量' }}</label>
              <input type="number" class="cs-input" v-model.number="form.quantity" min="1" step="1" />
            </div>
          </div>

          <div class="cs-form-field">
            <label class="cs-form-label">备注</label>
            <textarea v-model="form.note" class="cs-textarea" rows="2" :placeholder="mode === 'stockin' ? '例如：批量入库' : '例如：批量出库'" />
          </div>

          <button
            type="button"
            :class="['cs-submit-btn', canAdd ? (mode === 'stockin' ? 'cs-submit-primary' : 'cs-submit-danger') : 'cs-submit-disabled']"
            :disabled="!canAdd"
            @click="addStaged"
          >
            <FontAwesomeIcon icon="plus-circle" style="margin-right: 4px" />{{ mode === 'stockin' ? '新增入库' : '新增出库' }}
          </button>
        </form>
      </div>

      <!-- 右：暂存列表 + 批量导入 -->
      <div class="cs-right-col">
        <div class="cs-staged-section">
          <div class="cs-section-header">
            <div class="cs-section-title">
              <FontAwesomeIcon icon="layer-group" />
              {{ mode === 'stockin' ? '暂存入库列表' : '暂存出库列表' }}
            </div>
            <span class="cs-staged-count">共 {{ staged.length }} 个</span>
          </div>
          <div class="cs-staged-scroll">
            <div v-if="staged.length === 0" class="cs-staged-empty">
              <FontAwesomeIcon :icon="mode === 'stockin' ? 'box-open' : 'shipping-fast'" aria-hidden="true" />
              <p>{{ mode === 'stockin' ? '暂无暂存入库' : '暂无暂存出库' }}</p>
            </div>
            <div
              v-for="(item, idx) in staged"
              :key="item.id"
              :class="['cs-staged-item', mode === 'stockin' ? 'cs-staged-in' : 'cs-staged-out']"
            >
              <div class="cs-staged-info">
                <div class="cs-staged-product">
                  <FontAwesomeIcon icon="cubes" :style="{ color: mode === 'stockin' ? 'var(--color-primary-500)' : 'var(--color-danger-500)', marginRight: '4px' }" />
                  {{ item.productName }}
                </div>
                <div class="cs-staged-meta"><FontAwesomeIcon icon="user" style="margin-right: 4px" />{{ item.customer || '无客户' }}</div>
                <div class="cs-staged-badges">
                  <span :class="['cs-badge-tag', mode === 'stockin' ? 'cs-tag-info' : 'cs-tag-danger']">数量: {{ item.quantity }}</span>
                  <span class="cs-badge-tag cs-tag-secondary">{{ item.date }}</span>
                </div>
              </div>
              <button class="cs-icon-btn cs-icon-danger" @click="removeStagedItem(idx)" aria-label="删除"><FontAwesomeIcon icon="trash" /></button>
            </div>
          </div>
        </div>

        <!-- 批量导入 -->
        <div class="cs-batch-section">
          <div class="cs-section-header cs-collapsible" @click="showBatchUpload = !showBatchUpload">
            <div class="cs-section-title">
              <FontAwesomeIcon :icon="mode === 'stockin' ? 'file-import' : 'file-export'" :style="{ color: mode === 'stockin' ? 'var(--color-primary-500)' : 'var(--color-danger-500)' }" aria-hidden="true" />
              {{ mode === 'stockin' ? '批量导入入库' : '批量导出出库' }}
            </div>
            <FontAwesomeIcon icon="chevron-down" :class="['cs-collapse-arrow', { expanded: showBatchUpload }]" />
          </div>
          <div v-if="showBatchUpload" class="cs-batch-content">
            <UiUpload accept=".xlsx,.xls" placeholder="拖拽 Excel 文件到这里，或点击选择文件（支持 .xlsx / .xls）" @change="onExcelFileChange" />
            <div v-if="excelFile" class="cs-file-selected">
              <FontAwesomeIcon icon="file-excel" style="color: var(--color-success-500); margin-right: 6px" />{{ excelFile.name }}
            </div>
            <div class="cs-batch-actions">
              <button class="cs-action-btn cs-action-outline" :disabled="templateDownloading" @click="handleDownloadTemplate">
                <UiLoadingIcon :loading="templateDownloading" icon="file-excel" />下载模板
              </button>
              <button :class="['cs-action-btn', mode === 'stockin' ? 'cs-action-primary' : 'cs-action-danger']" :disabled="!excelFile || importing" @click="handleImportExcel">
                <i :loading="importing" icon="upload" style="margin-right: 4px" />{{ importing ? '导入中…' : '开始导入' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 提交按钮 -->
    <div class="cs-submit-bar">
      <button
        :class="['cs-submit-large', mode === 'stockin' ? 'cs-submit-primary' : 'cs-submit-danger']"
        :disabled="!staged.length"
        @click="submitBatch"
      >
        <FontAwesomeIcon icon="paper-plane" style="margin-right: 8px" />
        {{ submitting ? '提交中…' : mode === 'stockin' ? '提交入库' : '提交出库' }}
      </button>
    </div>

    <!-- 入库记录列表 -->
    <div class="cs-record-section">
      <div class="cs-section-header">
        <div class="cs-section-title">
          <FontAwesomeIcon icon="truck-loading" style="color: var(--color-primary-500)" />
          入库记录列表
        </div>
        <button class="cs-action-btn cs-action-outline" @click="siShowFilter = !siShowFilter">
          <FontAwesomeIcon icon="filter" style="margin-right: 4px" />筛选
        </button>
      </div>
      <div v-if="siShowFilter" class="cs-filter-panel">
        <div class="cs-filter-row">
          <div class="cs-filter-field">
            <label class="cs-form-label">客户</label>
            <UiSelect v-model="siFCustomer" placeholder="全部" :options="customerOptions" style="width: 100%" />
          </div>
          <div class="cs-filter-field">
            <label class="cs-form-label">开始日期</label>
            <UiDatePicker v-model="siFStart" style="width: 100%" />
          </div>
          <div class="cs-filter-field">
            <label class="cs-form-label">结束日期</label>
            <UiDatePicker v-model="siFEnd" style="width: 100%" />
          </div>
          <div class="cs-filter-action">
            <button class="cs-action-btn cs-action-primary" @click="siPage = 1; siRefetch()">
              <FontAwesomeIcon icon="search" style="margin-right: 4px" />查询
            </button>
          </div>
        </div>
      </div>
      <div v-if="siIsLoading && siList.length === 0" class="cs-loading"><UiSpinner /></div>
      <div v-else-if="siList.length === 0" class="cs-empty"><FontAwesomeIcon icon="inbox" /><span>暂无入库记录</span></div>
      <template v-else>
      <div v-if="siIsFetching" class="cs-fetching-bar"><div class="cs-fetching-progress" /></div>
      <table class="cs-table">
        <thead>
          <tr>
            <th>入库日期</th>
            <th>客户</th>
            <th style="text-align: left">产品名称</th>
            <th>69码</th>
            <th style="text-align: right">数量</th>
            <th>备注</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in siList" :key="row.id">
            <td>{{ row.stockin_date }}</td>
            <td>{{ row.customer || '-' }}</td>
            <td style="text-align: left">{{ row.case_name }}</td>
            <td><small>{{ row.case_barcode || '-' }}</small></td>
            <td style="text-align: right"><strong>{{ row.quantity }}</strong></td>
            <td><small>{{ row.note || '-' }}</small></td>
            <td>
              <button class="cs-icon-btn cs-icon-warning" @click="openEditModal('stockin', row)" aria-label="编辑"><FontAwesomeIcon icon="edit" /></button>
              <button class="cs-icon-btn cs-icon-danger" :disabled="actionId === row.id" @click="handleDelete('stockin', row)" aria-label="删除"><FontAwesomeIcon icon="trash" /></button>
            </td>
          </tr>
        </tbody>
      </table>
      <UiPagination v-if="siTotalPages > 1" :current-page="siPage" :total-pages="siTotalPages" @update:current-page="siPage = $event; siRefetch()" />
      </template>
    </div>

    <!-- 出库记录列表 -->
    <div class="cs-record-section">
      <div class="cs-section-header">
        <div class="cs-section-title">
          <FontAwesomeIcon icon="shipping-fast" style="color: var(--color-danger-500)" />
          出库记录列表
        </div>
        <button class="cs-action-btn cs-action-outline" @click="soShowFilter = !soShowFilter">
          <FontAwesomeIcon icon="filter" style="margin-right: 4px" />筛选
        </button>
      </div>
      <div v-if="soShowFilter" class="cs-filter-panel">
        <div class="cs-filter-row">
          <div class="cs-filter-field">
            <label class="cs-form-label">客户</label>
            <UiSelect v-model="soFCustomer" placeholder="全部" :options="customerOptions" style="width: 100%" />
          </div>
          <div class="cs-filter-field">
            <label class="cs-form-label">开始日期</label>
            <UiDatePicker v-model="soFStart" style="width: 100%" />
          </div>
          <div class="cs-filter-field">
            <label class="cs-form-label">结束日期</label>
            <UiDatePicker v-model="soFEnd" style="width: 100%" />
          </div>
          <div class="cs-filter-action">
            <button class="cs-action-btn cs-action-primary" @click="soPage = 1; soRefetch()">
              <FontAwesomeIcon icon="search" style="margin-right: 4px" />查询
            </button>
          </div>
        </div>
      </div>
      <div v-if="soIsLoading && soList.length === 0" class="cs-loading"><UiSpinner /></div>
      <div v-else-if="soList.length === 0" class="cs-empty"><FontAwesomeIcon icon="inbox" /><span>暂无出库记录</span></div>
      <template v-else>
      <div v-if="soIsFetching" class="cs-fetching-bar"><div class="cs-fetching-progress" /></div>
      <table class="cs-table">
        <thead>
          <tr>
            <th>出库日期</th>
            <th>客户</th>
            <th style="text-align: left">产品名称</th>
            <th>69码</th>
            <th style="text-align: right">数量</th>
            <th>备注</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in soList" :key="row.id">
            <td>{{ row.stockout_date }}</td>
            <td>{{ row.customer || '-' }}</td>
            <td style="text-align: left">{{ row.case_name }}</td>
            <td><small>{{ row.case_barcode || '-' }}</small></td>
            <td style="text-align: right"><strong style="color: var(--color-danger-500)">{{ row.quantity }}</strong></td>
            <td><small>{{ row.note || '-' }}</small></td>
            <td>
              <button class="cs-icon-btn cs-icon-warning" @click="openEditModal('stockout', row)" aria-label="编辑"><FontAwesomeIcon icon="edit" /></button>
              <button class="cs-icon-btn cs-icon-danger" :disabled="actionId === row.id" @click="handleDelete('stockout', row)" aria-label="删除"><FontAwesomeIcon icon="trash" /></button>
            </td>
          </tr>
        </tbody>
      </table>
      <UiPagination v-if="soTotalPages > 1" :current-page="soPage" :total-pages="soTotalPages" @update:current-page="soPage = $event; soRefetch()" />
      </template>
    </div>

    <!-- 编辑弹窗 -->
    <UiDialog v-model:open="editDialogOpen" :title="editMode === 'stockin' ? '编辑入库记录' : '编辑出库记录'" max-width-class="max-w-[500px]">
      <div class="cs-edit-form">
        <div class="cs-form-field">
          <label class="cs-form-label">客户名称</label>
          <UiSelect v-model="editForm.customer" :options="editMode === 'stockout' ? [{ value: '', label: '无' }, ...customerOptions] : customerOptions" />
        </div>
        <div class="cs-form-field">
          <label class="cs-form-label">{{ editMode === 'stockin' ? '入库日期' : '出库日期' }}</label>
          <UiDatePicker v-model="editForm.date" style="width: 100%" />
        </div>
        <div class="cs-form-field">
          <label class="cs-form-label">产品名称</label>
          <input class="cs-input" :value="editForm.productName" disabled />
        </div>
        <div class="cs-form-field">
          <label class="cs-form-label">{{ editMode === 'stockin' ? '入库数量' : '出库数量' }}</label>
          <input type="number" class="cs-input" v-model.number="editForm.quantity" min="1" step="1" />
        </div>
        <div class="cs-form-field">
          <label class="cs-form-label">备注</label>
          <textarea v-model="editForm.note" class="cs-textarea" rows="2" />
        </div>
      </div>
      <template #footer>
        <button class="cs-action-btn cs-action-outline" @click="editDialogOpen = false">取消</button>
        <button class="cs-action-btn cs-action-primary" @click="saveEdit">保存</button>
      </template>
    </UiDialog>

    <UiConfirmDialog
      :open="confirmDialog.open"
      :text="confirmDialog.text"
      :sub="confirmDialog.sub"
      :type="confirmDialog.type"
      @confirm="confirmDialog.onConfirm"
      @cancel="confirmDialog.onCancel"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onUnmounted } from 'vue'
import { useQuery, keepPreviousData } from '@tanstack/vue-query'
import { caseApi, customerApi } from '@/api'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiUpload from '@/components/ui/UiUpload.vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import { showToast } from '@/composables/useToast'
import { toISODate } from '@/utils/format'
import { useCaseStockActions } from './composables/useCaseStockActions'

// === 模式 ===
const mode = ref<'stockin' | 'stockout'>('stockin')

function switchMode(nextMode: 'stockin' | 'stockout') {
  mode.value = nextMode
  form.customer = ''
  form.date = today
  form.search = ''
  form.productId = ''
  form.quantity = 1
  form.note = ''
  currentStock.value = 0
  staged.value = []
  showSuggestions.value = false
  excelFile.value = null
}

// === 客户列表 ===
const { data: customersData } = useQuery({
  queryKey: ['case-customer-names'],
  queryFn: async () => {
    const res = (await customerApi.activeNames()) as any
    return res.names ?? res ?? []
  },
  staleTime: 30_000,
})
const customers = computed(() => (Array.isArray(customersData.value) ? customersData.value : []))
const customerOptions = computed(() => customers.value.map((c: string) => ({ value: c, label: c })))

// === 产品搜索 ===
async function searchCaseProducts(query: string) {
  if (!query.trim()) return []
  try {
    const data = await caseApi.search(query)
    return Array.isArray(data) ? data : []
  } catch {
    return []
  }
}

const currentStock = ref(0)

function onProductSelect(product: any) {
  form.productId = String(product.id)
  form.search = product.name
  if (mode.value === 'stockout') currentStock.value = product.current_stock ?? 0
}

// === 表单 ===
const today = toISODate()
const form = reactive({ customer: '', date: today, search: '', productId: '', quantity: 1, note: '' })

const canAdd = computed(() => {
  if (!form.productId || form.quantity < 1 || !form.date) return false
  if (mode.value === 'stockin' && !form.customer) return false
  if (mode.value === 'stockout' && form.quantity > currentStock.value) return false
  return true
})

// === 暂存列表 ===
const staged = ref<any[]>([])

const {
  confirmDialog,
  submitting,
  submitBatch,
  showBatchUpload,
  excelFile,
  importing,
  templateDownloading,
  onExcelFileChange,
  handleDownloadTemplate,
  handleImportExcel,
  actionId,
  handleDelete,
  editDialogOpen,
  editMode,
  editForm,
  openEditModal,
  saveEdit,
} = useCaseStockActions(mode, staged, currentStock)

async function removeStagedItem(idx: number) {
  const ok = await confirmDialog.confirm('确定删除？', '此操作不可恢复', 'danger')
  if (!ok) return
  staged.value.splice(idx, 1)
}

function addStaged() {
  if (!canAdd.value) {
    if (mode.value === 'stockout' && form.quantity > currentStock.value) {
      showToast(`库存不足，当前库存: ${currentStock.value}`, 'warning')
    } else {
      showToast('请选择产品并输入数量', 'warning')
    }
    return
  }
  staged.value.push({
    id: Date.now(),
    productId: form.productId,
    productName: form.search,
    customer: form.customer,
    date: form.date,
    quantity: form.quantity,
    note: form.note,
  })
  if (mode.value === 'stockout') currentStock.value -= form.quantity
  form.search = ''
  form.productId = ''
  form.quantity = 1
  form.note = ''
}

// === 入库记录列表 ===
const siShowFilter = ref(false)
const siFCustomer = ref('')
const siFStart = ref('')
const siFEnd = ref('')
const siPage = ref(1)
const siTotalPages = ref(1)

const {
  data: siData,
  isLoading: siIsLoading,
  isFetching: siIsFetching,
  refetch: siRefetch,
} = useQuery({
  queryKey: ['case-stockins', siPage, siFCustomer, siFStart, siFEnd],
  queryFn: async () => {
    const params: Record<string, any> = { page: siPage.value, per_page: 10 }
    if (siFCustomer.value) params.customer = siFCustomer.value
    if (siFStart.value) params.start_date = siFStart.value
    if (siFEnd.value) params.end_date = siFEnd.value
    const res = (await caseApi.stockins(params)) as any
    siTotalPages.value = res.pages ?? res.total_pages ?? 1
    return res
  },
  staleTime: 30_000,
  placeholderData: keepPreviousData,
})
const siList = computed(() => siData.value?.stockins ?? siData.value?.items ?? [])

// === 出库记录列表 ===
const soShowFilter = ref(false)
const soFCustomer = ref('')
const soFStart = ref('')
const soFEnd = ref('')
const soPage = ref(1)
const soTotalPages = ref(1)

const {
  data: soData,
  isLoading: soIsLoading,
  isFetching: soIsFetching,
  refetch: soRefetch,
} = useQuery({
  queryKey: ['case-stockouts', soPage, soFCustomer, soFStart, soFEnd],
  queryFn: async () => {
    const params: Record<string, any> = { page: soPage.value, per_page: 10 }
    if (soFCustomer.value) params.customer = soFCustomer.value
    if (soFStart.value) params.start_date = soFStart.value
    if (soFEnd.value) params.end_date = soFEnd.value
    const res = (await caseApi.stockouts(params)) as any
    soTotalPages.value = res.pages ?? res.total_pages ?? 1
    return res
  },
  staleTime: 30_000,
  placeholderData: keepPreviousData,
})
const soList = computed(() => soData.value?.stockouts ?? soData.value?.items ?? [])
</script>

<style scoped>
.cs-stock {
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* Mode toggle */
.cs-mode-toggle {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light, #e2e8f0);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  align-self: flex-start;
}
.cs-mode-btn {
  padding: 8px 14px;
  font-size: 13px;
  font-weight: 600;
  border: none;
  border-radius: 9px;
  background: transparent;
  cursor: pointer;
  color: var(--color-text-secondary);
  transition: background 0.3s ease, color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
  display: flex;
  align-items: center;
  gap: 6px;
}
.cs-mode-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}
.cs-mode-btn.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91, 141, 239, 0.2);
  transform: translateY(-1px);
}
.cs-mode-btn.active.out-mode {
  background: linear-gradient(135deg, var(--color-danger-50), var(--color-danger-100));
  color: var(--color-danger-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(234, 84, 85, 0.2);
}

/* Section headers */
.cs-section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
}
.cs-section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
}
.cs-section-title i {
  font-size: 14px;
}
.cs-collapsible {
  cursor: pointer;
}

/* Top row */
.cs-top-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
@media (max-width: 992px) {
  .cs-top-row { grid-template-columns: 1fr; }
}
.cs-form-section, .cs-staged-section, .cs-batch-section, .cs-record-section {
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 13px;
  overflow: hidden;
  background: var(--color-surface-card, white);
}
.cs-right-col {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* Form */
.cs-form {
  padding: 16px;
}
.cs-form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.cs-form-field {
  margin-bottom: 12px;
}
.cs-form-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--color-text-secondary);
  margin-bottom: 6px;
}
.cs-input {
  width: 100%;
  padding: 8px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  font-size: 14px;
  color: var(--color-text);
  font-family: inherit;
  background: white;
  outline: none;
  transition: border-color 0.3s ease, background 0.3s ease, box-shadow 0.3s ease;
}
.cs-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.cs-input:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.cs-textarea {
  width: 100%;
  padding: 8px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  font-size: 14px;
  color: var(--color-text);
  resize: vertical;
  font-family: inherit;
  background: white;
  outline: none;
  transition: border-color 0.3s ease, background 0.3s ease, box-shadow 0.3s ease;
}
.cs-textarea:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.cs-textarea:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.cs-current-stock {
  display: block;
  margin-top: 4px;
  color: var(--color-text-secondary);
  font-size: 12px;
}

/* Submit buttons */
.cs-submit-btn {
  width: 100%;
  padding: 9px 14px;
  border: none;
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.3s ease, border-color 0.3s ease, transform 0.3s ease;
  display: flex;
  align-items: center;
  justify-content: center;
}
.cs-submit-primary { background: var(--color-primary-50); color: var(--color-primary-600); border: 2px solid var(--color-primary-300); }
.cs-submit-primary:hover { background: var(--color-primary-100); transform: translateY(-1px); }
.cs-submit-danger { background: var(--color-danger-50); color: var(--color-danger-600); border: 2px solid var(--color-danger-300); }
.cs-submit-danger:hover { background: var(--color-danger-100); transform: translateY(-1px); }
.cs-submit-disabled { background: var(--color-surface, #f8fafc); color: var(--color-text-muted); border: 2px solid var(--color-border-light); cursor: not-allowed; opacity: 0.4; }

.cs-submit-bar {
  text-align: center;
  padding: 8px 0;
}
.cs-submit-large {
  min-width: 200px;
  padding: 12px 24px;
  border: none;
  border-radius: 9px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: box-shadow 0.3s ease, transform 0.3s ease;
  color: white;
}
.cs-submit-large.cs-submit-primary { background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700)); }
.cs-submit-large.cs-submit-primary:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(91, 141, 239, 0.3); }
.cs-submit-large.cs-submit-danger { background: linear-gradient(135deg, var(--color-danger-500), var(--color-danger-700)); }
.cs-submit-large.cs-submit-danger:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(234, 84, 85, 0.3); }
.cs-submit-large:disabled { opacity: 0.4; cursor: not-allowed; }

/* Badges */
.cs-badge {
  padding: 4px 10px;
  border-radius: 16px;
  font-size: 12px;
  font-weight: 600;
}
.cs-badge-info { background: var(--color-primary-50); color: var(--color-primary-600); }
.cs-badge-danger { background: var(--color-danger-50); color: var(--color-danger-600); }

/* Staged list */
.cs-staged-scroll {
  max-height: 350px;
  overflow-y: auto;
  padding: 12px 16px;
}
.cs-staged-empty {
  text-align: center;
  color: var(--color-text-muted);
  padding: 32px 0;
}
.cs-staged-empty i { font-size: 28px; opacity: 0.3; display: block; margin-bottom: 8px; }
.cs-staged-count { color: var(--color-text-secondary); font-size: 13px; }
.cs-staged-item {
  border: 2px solid;
  border-radius: 10px;
  padding: 10px 14px;
  margin-bottom: 8px;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  transition: transform 0.3s ease;
}
.cs-staged-item:hover { transform: translateY(-1px); }
.cs-staged-in { border-color: var(--color-primary-200); }
.cs-staged-out { border-color: var(--color-danger-100); }
.cs-staged-info { flex: 1; }
.cs-staged-product { font-weight: 600; margin-bottom: 4px; font-size: 13px; }
.cs-staged-meta { color: var(--color-text-secondary); font-size: 12px; margin-bottom: 4px; }
.cs-staged-badges { display: flex; gap: 6px; }
.cs-badge-tag { padding: 2px 8px; border-radius: 99px; font-size: 11px; font-weight: 500; }
.cs-tag-info { background: var(--color-info-50); color: var(--color-info-700); }
.cs-tag-danger { background: var(--color-danger-50); color: var(--color-danger-700); }
.cs-tag-secondary { background: var(--color-border-light); color: var(--color-text-secondary); }

/* Icon buttons */
.cs-icon-btn {
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 7px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 12px;
  transition: background 0.2s ease;
}
.cs-icon-danger { background: var(--color-danger-50); color: var(--color-danger-500); }
.cs-icon-danger:hover { background: var(--color-danger-100); }
.cs-icon-warning { background: var(--color-warning-50); color: var(--color-warning-500); }
.cs-icon-warning:hover { background: var(--color-warning-100); }

/* Action buttons */
.cs-action-btn {
  padding: 6px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  background: white;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s ease;
  color: var(--color-text-secondary);
}
.cs-action-primary { color: var(--color-primary-600); }
.cs-action-primary:hover:not(:disabled) { background: var(--color-primary-50); border-color: var(--color-primary-300); transform: translateY(-1px); }
.cs-action-danger { color: var(--color-danger-500); }
.cs-action-danger:hover:not(:disabled) { background: var(--color-danger-50); border-color: var(--color-danger-200); transform: translateY(-1px); }
.cs-action-outline { }
.cs-action-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* Batch */
.cs-batch-content { padding: 12px 16px; }
.cs-file-selected { margin-top: 8px; font-size: 13px; color: var(--color-text-secondary); }
.cs-batch-actions { display: flex; justify-content: space-between; align-items: center; margin-top: 12px; }

/* Collapse arrow */
.cs-collapse-arrow { color: var(--color-text-muted); transition: transform 0.25s ease; }
.cs-collapse-arrow.expanded { transform: rotate(180deg); }

/* Filter panel */
.cs-filter-panel { border-bottom: 1px solid var(--color-border-light); padding: 12px 16px; }
.cs-filter-row { display: flex; gap: 12px; flex-wrap: wrap; align-items: flex-end; }
.cs-filter-field { flex: 0 0 auto; }
.cs-filter-action { display: flex; align-items: flex-end; }

/* Table */
.cs-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.cs-table thead th {
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
.cs-table tbody td {
  padding: 10px 14px;
  font-size: 13px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  text-align: center;
  vertical-align: middle;
  transition: background 0.2s ease;
  color: var(--color-text);
}
.cs-table tbody tr:hover { background: var(--color-primary-50); }

/* Loading & Empty */
.cs-loading, .cs-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 32px 0;
  color: var(--color-text-muted);
}
.cs-empty {
  flex-direction: column;
}
.cs-empty i { font-size: 28px; opacity: 0.5; }

/* Fetching progress bar */
.cs-fetching-bar {
  height: 2px;
  background: var(--color-primary-100, #e0f2fe);
  overflow: hidden;
  border-radius: 1px;
}
.cs-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500, #3b82f6);
  border-radius: 1px;
  animation: cs-progress-slide 1s ease-in-out infinite;
}
@keyframes cs-progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}

/* Autocomplete */
.cs-autocomplete-dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  z-index: 1000;
  background: white;
  border: 2px solid var(--color-primary-200);
  border-radius: 12px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.12);
  max-height: 200px;
  overflow-y: auto;
}
.cs-autocomplete-item {
  padding: 10px 14px;
  cursor: pointer;
  transition: background 0.2s ease;
  border-bottom: 1px solid var(--color-border-light);
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
}
.cs-autocomplete-item:last-child { border-bottom: none; }
.cs-autocomplete-item:hover { background: var(--color-primary-50); }
.cs-barcode-hint { color: var(--color-text-muted); font-size: 11px; }

/* Edit form */
.cs-edit-form {
  display: flex;
  flex-direction: column;
  gap: 0;
}
</style>
