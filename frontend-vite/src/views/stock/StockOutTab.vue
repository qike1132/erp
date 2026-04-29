<template>
  <div class="stock-out-tab">
    <!-- TAB: 录入 -->
    <div v-show="activeTab === 'input'" class="so-tab-content">
      <div class="so-body">
        <!-- 左栏：出货信息录入 -->
        <div class="so-col">
          <div class="so-col-title">
            <span><i class="fas fa-shipping-fast"></i> 出货信息录入</span>
            <UiBadge v-if="staged.length" variant="cancelled">已暂存: {{ staged.length }}</UiBadge>
          </div>
          <div class="so-col-scroll">
            <form @submit.prevent>
              <div class="form-grid">
                <div class="form-field">
                  <label class="form-label"><i class="fas fa-calendar-alt label-icon"></i>出货时间</label>
                  <UiDatePicker v-model="form.date" style="width: 100%" />
                </div>
                <div class="form-field">
                  <label class="form-label"><i class="fas fa-user label-icon"></i>客户名称</label>
                  <UiSelect v-model="form.customer" placeholder="请选择客户" :options="customerOptions" />
                </div>
              </div>

              <div class="form-field" style="position: relative">
                <label class="form-label"><i class="fas fa-search label-icon"></i>产品名称</label>
                <input
                  type="text"
                  class="form-text-input"
                  :value="form.search"
                  placeholder="输入产品名称或69码搜索"
                  @input="form.search = ($event.target as HTMLInputElement).value; onSearchInput()"
                  @focus="onProductFocus"
                  @blur="hideSuggestions"
                />
                <div v-if="productSuggestions.length && showSuggestions" class="autocomplete-dropdown">
                  <div
                    v-for="p in productSuggestions"
                    :key="p.id"
                    class="autocomplete-item"
                    @mousedown.prevent="selectProduct(p)"
                  >
                    {{ p.name }}
                    <span v-if="p.barcode" class="barcode-hint">{{ p.barcode }}</span>
                  </div>
                </div>
              </div>

              <div class="form-field">
                <label class="form-label"><i class="fas fa-cubes label-icon"></i>出货数量</label>
                <input type="number" class="form-input" v-model.number="form.quantity" min="1" step="1" />
                <small v-if="shipmentInfo" class="shipment-info">
                  <i class="fas fa-info-circle" style="margin-right: 4px" />
                  订单量: {{ shipmentInfo.order_quantity }} | 已出货: {{ shipmentInfo.shipped_quantity }} | 可出货:
                  <strong style="color: var(--color-primary-500)">{{ shipmentInfo.available_quantity }}</strong>
                </small>
              </div>

              <div class="form-field">
                <label class="form-label"><i class="fas fa-sticky-note label-icon"></i>备注</label>
                <textarea
                  v-model="form.note"
                  class="form-input"
                  rows="2"
                  placeholder="例如：物流发货"
                />
              </div>

              <!-- 批量导入出货 -->
              <div class="so-section-label"><i class="fas fa-file-import"></i> 批量导入</div>
              <div
                class="so-section-header so-droppable"
                :class="{ 'so-drag-over': excelDragOver }"
                @click="excelInputRef?.click()"
                @dragover.prevent="excelDragOver = true"
                @dragleave="excelDragOver = false"
                @drop.prevent="onExcelDrop"
              >
                <label class="form-label so-droppable-label">
                  <i class="fas fa-file-excel label-icon"></i>
                  <span v-if="excelFile" class="so-file-inline so-file-inline-success"><i class="fas fa-file-excel" />{{ excelFile.name }}</span>
                  <span v-else>拖拽文件到标题栏 · 支持 .xlsx / .xls</span>
                </label>
                <div class="so-inline-actions">
                  <button class="so-inline-btn" :disabled="templateDownloading" @click.stop="handleDownloadTemplate">
                    <i :class="templateDownloading ? 'fas fa-spinner fa-spin' : 'fas fa-download'" />模板
                  </button>
                  <button class="so-inline-btn so-inline-btn-success" :disabled="!excelFile || importing" @click.stop="handleImportExcel">
                    <i :class="importing ? 'fas fa-spinner fa-spin' : 'fas fa-upload'" />{{
                      importing ? '导入中' : '导入'
                    }}
                  </button>
                </div>
                <input
                  ref="excelInputRef"
                  type="file"
                  accept=".xlsx,.xls"
                  style="display: none"
                  @change="onExcelFileSelect"
                />
              </div>

              <!-- OCR 识别 -->
              <div class="so-section-label"><i class="fas fa-file-pdf"></i> OCR 识别</div>
              <div
                class="so-section-header so-droppable so-droppable-danger"
                :class="{ 'so-drag-over': ocrDragOver }"
                @click="ocrInputRef?.click()"
                @dragover.prevent="ocrDragOver = true"
                @dragleave="ocrDragOver = false"
                @drop.prevent="onOcrDrop"
              >
                <label class="form-label so-droppable-label">
                  <i class="fas fa-file-pdf label-icon"></i>
                  <span v-if="pdfFiles.length" class="so-file-inline so-file-inline-danger"><i class="fas fa-file-image" />已选 {{ pdfFiles.length }} 个文件</span>
                  <span v-else>拖拽文件到标题栏 · 支持 PDF / PNG / JPG / BMP / TIFF</span>
                </label>
                <div class="so-inline-actions">
                  <button class="so-inline-btn" :disabled="!pdfFiles.length || ocrPreviewing" @click.stop="handleOcrPreview">
                    <i :class="ocrPreviewing ? 'fas fa-spinner fa-spin' : 'fas fa-eye'" />预览
                  </button>
                  <button class="so-inline-btn so-inline-btn-danger" :disabled="!pdfFiles.length || ocrImporting" @click.stop="handleOcrImport">
                    <i :class="ocrImporting ? 'fas fa-spinner fa-spin' : 'fas fa-magic'" />导入
                  </button>
                </div>
                <input
                  ref="ocrInputRef"
                  type="file"
                  accept=".pdf,.png,.jpg,.jpeg,.bmp,.tiff,.tif,.webp"
                  multiple
                  style="display: none"
                  @change="onOcrFileSelect"
                />
              </div>
              <div v-if="ocrProgress.show" class="so-section-body so-section-body-compact">
                <div class="ocr-progress">
                  <div class="ocr-progress-bar">
                    <div class="ocr-progress-fill" :style="{ width: ocrProgress.pct + '%' }" />
                  </div>
                  <div class="ocr-progress-text">
                    <small>{{ ocrProgress.msg }}</small>
                    <small style="font-weight: 700; color: var(--color-danger-500)">{{ ocrProgress.pct }}%</small>
                  </div>
                </div>
              </div>

              <UiButton
                :variant="canAdd ? 'danger' : 'outline'"
                :disabled="!canAdd"
                @click="addStaged"
                style="margin-top: 15px"
              >
                <i class="fas fa-plus-circle" />新增出货
              </UiButton>
            </form>
          </div>
        </div>

        <!-- 右栏：暂存列表 -->
        <div class="so-col">
          <div class="so-col-title">
            <span><i class="fas fa-clipboard-list"></i> 暂存出货列表</span>
            <span class="staged-count">共 {{ staged.length }} 个，合计 {{ stagedTotalQty }}</span>
          </div>
          <div class="so-col-scroll">
            <div v-if="staged.length === 0" class="so-empty-state">
              <i class="fas fa-box-open so-empty-icon" />
              <p>暂无暂存出货</p>
            </div>
            <TransitionGroup v-else name="staged-list" tag="div">
              <div
                v-for="(item, idx) in staged"
                :key="item.id"
                class="so-staged-card"
              >
                <div class="so-staged-main">
                  <div class="so-staged-info">
                    <div class="so-staged-product">
                      <i class="fas fa-shipping-fast so-staged-icon" />{{ item.productName }}
                    </div>
                    <div class="so-staged-meta">
                      <span class="so-staged-tag"><i class="fas fa-user" />{{ item.customer || '无客户' }}</span>
                      <span class="so-staged-tag"><i class="fas fa-calendar-alt" />{{ item.date }}</span>
                    </div>
                    <div class="so-staged-badges">
                      <span class="badge-tag badge-danger">数量: {{ item.quantity }}</span>
                      <span v-if="item.note" class="badge-tag badge-secondary">备注: {{ item.note }}</span>
                    </div>
                  </div>
                  <div class="so-staged-actions">
                    <button class="action-btn action-edit" @click="openEditStaged(idx)">
                      <i class="fas fa-edit" />
                    </button>
                    <button class="action-btn action-delete" @click="staged.splice(idx, 1)">
                      <i class="fas fa-trash" />
                    </button>
                  </div>
                </div>
              </div>
            </TransitionGroup>
          </div>
        </div>
      </div>

      <!-- 提交按钮 -->
      <div v-if="staged.length" class="so-submit-bar">
        <UiButton
          variant="danger"
          size="lg"
          :disabled="submitting"
          @click="submitBatch"
        >
          <i class="fas fa-paper-plane" style="margin-right: 6px" />
          {{ submitting ? '提交中...' : '添加出货' }}
        </UiButton>
      </div>
    </div>

    <!-- TAB: 记录查询 -->
    <div v-show="activeTab === 'records'" class="so-tab-content">
      <div class="so-records-header">
        <span class="so-records-title"><i class="fas fa-list-alt"></i> 出货记录列表</span>
        <UiButton variant="outline" size="sm" @click="showFilter = !showFilter">
          <i class="fas fa-filter" style="margin-right: 4px" />筛选
        </UiButton>
      </div>

      <div v-if="showFilter" class="filter-panel">
        <div class="filter-row">
          <div class="filter-field">
            <label class="form-label"><i class="fas fa-user label-icon"></i>客户</label>
            <UiSelect v-model="filterCustomer" placeholder="全部" :options="customerOptions" style="width: 100%" />
          </div>
          <div class="filter-field">
            <label class="form-label"><i class="fas fa-calendar-alt label-icon"></i>开始日期</label>
            <UiDatePicker v-model="filterStart" style="width: 100%" />
          </div>
          <div class="filter-field">
            <label class="form-label"><i class="fas fa-calendar-alt label-icon"></i>结束日期</label>
            <UiDatePicker v-model="filterEnd" style="width: 100%" />
          </div>
          <div class="filter-field filter-action">
            <UiButton variant="primary" size="sm" @click="fetchStockouts">
              <i class="fas fa-search" style="margin-right: 4px" />查询
            </UiButton>
          </div>
        </div>
      </div>

      <div class="so-records-body">
        <div v-if="isLoading" class="state-placeholder">
          <div class="spinner-ring" />
          <p class="state-text">加载中...</p>
        </div>
        <div v-else-if="stockoutRecords.length === 0" class="state-placeholder state-empty">
          <div class="empty-illustration"><i class="fas fa-shipping-fast" /></div>
          <p class="state-text">暂无出货记录</p>
        </div>

        <div v-else>
          <div v-for="group in groupedRecords" :key="group.date" class="date-group">
            <div class="date-group-header" @click="group.expanded = !group.expanded">
              <div class="date-group-title">
                <i class="fas fa-calendar-alt" style="color: var(--color-danger-500); margin-right: 8px" />
                <strong>{{ group.date }}</strong>
                <span class="badge-tag badge-info">{{ group.records.length }} 条记录</span>
                <span class="badge-tag badge-secondary">共 {{ group.totalQty }} 件</span>
              </div>
              <i :class="['fas fa-chevron-down toggle-icon', { expanded: group.expanded }]" />
            </div>
            <Transition name="group-expand">
              <div v-if="group.expanded" class="date-group-content">
                <table class="so-table">
                  <thead>
                    <tr>
                      <th>客户</th>
                      <th>产品图片</th>
                      <th style="text-align: left">产品名称</th>
                      <th>69码</th>
                      <th>数量</th>
                      <th>抵扣备货</th>
                      <th>备注</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="item in group.summaryList" :key="item.key">
                      <td><span class="cell-main">{{ item.customer }}</span></td>
                      <td>
                        <img
                          v-if="item.productImage"
                          :src="item.productImage"
                          class="product-thumb"
                        />
                        <span v-else class="cell-muted">-</span>
                      </td>
                      <td style="text-align: left"><span class="cell-main">{{ item.productName }}</span></td>
                      <td><span class="cell-muted">{{ item.barcode || '-' }}</span></td>
                      <td><strong>{{ item.quantity }}</strong></td>
                      <td>
                        <span v-if="item.deductQuantity > 0" class="badge-tag badge-success">抵扣: {{ item.deductQuantity }}</span>
                        <span v-else class="badge-tag badge-muted">否</span>
                      </td>
                      <td><span class="cell-muted">{{ item.notesDisplay }}</span></td>
                      <td>
                        <div class="action-group">
                          <button class="action-btn action-edit" @click="openEditRecord(item)">
                            <i class="fas fa-edit" />
                          </button>
                          <button
                            class="action-btn action-delete"
                            :disabled="actionId === item.firstId"
                            @click="handleDeleteRecord(item.firstId)"
                          >
                            <i class="fas fa-trash" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </Transition>
          </div>
        </div>

        <div v-if="totalPages > 1" class="pagination-wrap">
          <UiPagination
            :current-page="currentPage"
            :total-pages="totalPages"
            @update:current-page="currentPage = $event; fetchStockouts()"
          />
        </div>
      </div>
    </div>

    <!-- 编辑暂存出货弹窗 -->
    <UiDialog v-model:open="editStagedOpen" title="编辑暂存出货" max-width-class="max-w-[500px]">
      <div class="dialog-form">
        <div class="form-field">
          <label class="form-label"><i class="fas fa-calendar-alt label-icon"></i>出货时间</label>
          <UiDatePicker v-model="editStagedForm.date" style="width: 100%" />
        </div>
        <div class="form-field">
          <label class="form-label"><i class="fas fa-user label-icon"></i>客户名称</label>
          <UiSelect v-model="editStagedForm.customer" :options="customerOptions" />
        </div>
        <div class="form-field">
          <label class="form-label"><i class="fas fa-box label-icon"></i>产品名称</label>
          <UiInput :model-value="editStagedForm.productName" disabled />
        </div>
        <div class="form-field">
          <label class="form-label"><i class="fas fa-cubes label-icon"></i>出货数量</label>
          <input type="number" class="form-input" v-model.number="editStagedForm.quantity" min="1" step="1" />
        </div>
        <div class="form-field">
          <label class="form-label"><i class="fas fa-sticky-note label-icon"></i>备注</label>
          <textarea v-model="editStagedForm.note" class="form-input" rows="2" />
        </div>
      </div>
      <template #footer>
        <UiButton variant="outline" @click="editStagedOpen = false">取消</UiButton>
        <UiButton variant="primary" @click="saveEditStaged">保存</UiButton>
      </template>
    </UiDialog>

    <!-- 编辑出货记录弹窗 -->
    <UiDialog v-model:open="editRecordOpen" title="编辑出货记录" max-width-class="max-w-[500px]">
      <div class="dialog-form">
        <div class="form-field">
          <label class="form-label"><i class="fas fa-calendar-alt label-icon"></i>出货时间</label>
          <UiDatePicker v-model="editRecordForm.date" style="width: 100%" />
        </div>
        <div class="form-field">
          <label class="form-label"><i class="fas fa-user label-icon"></i>客户名称</label>
          <UiSelect
            v-model="editRecordForm.customer"
            :options="[{ value: '', label: '无' }, ...customerOptions]"
          />
        </div>
        <div class="form-field">
          <label class="form-label"><i class="fas fa-box label-icon"></i>产品名称</label>
          <UiInput :model-value="editRecordForm.productName" disabled />
        </div>
        <div class="form-field">
          <label class="form-label"><i class="fas fa-cubes label-icon"></i>出货数量</label>
          <input type="number" class="form-input" v-model.number="editRecordForm.quantity" min="1" step="1" />
        </div>
        <div class="form-field">
          <label class="form-label"><i class="fas fa-sticky-note label-icon"></i>备注</label>
          <textarea v-model="editRecordForm.note" class="form-input" rows="2" />
        </div>
      </div>
      <template #footer>
        <UiButton variant="outline" @click="editRecordOpen = false">取消</UiButton>
        <UiButton variant="primary" @click="saveEditRecord">保存</UiButton>
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
import { ref, reactive, computed } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { get, post, put, del, upload, download } from '@/api/request'
import { customerApi, stockApi, auxApi, ocrApi } from '@/api'

const props = defineProps<{ activeTab: 'input' | 'records' }>()
import UiInput from '@/components/ui/UiInput.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { showToast } from '@/composables/useToast'

const queryClient = useQueryClient()
const confirmDialog = useConfirmDialog()
const actionId = ref<number | ''>(0)

// === 客户列表 ===
import { useQuery } from '@tanstack/vue-query'
import { watch } from 'vue'

const { data: namesData } = useQuery({
  queryKey: ['customer-active-names'],
  queryFn: async () => { const res = await customerApi.activeNames() as any; return res.names ?? res ?? [] },
  staleTime: 30_000,
})
const customerNames = computed(() => {
  const arr = Array.isArray(namesData.value) ? namesData.value : []
  return arr.map((c: any) => c.name ?? c)
})
const customerOptions = computed(() => customerNames.value.map((c: string) => ({ value: c, label: c })))

// === 产品搜索 ===
const productSuggestions = ref<any[]>([])
const showSuggestions = ref(false)
let searchTimeout: ReturnType<typeof setTimeout> | null = null

async function searchProducts(q: string) {
  if (!q.trim()) { productSuggestions.value = []; showSuggestions.value = false; return }
  try {
    const data = await stockApi.searchProducts(q) as any
    productSuggestions.value = Array.isArray(data) ? data : data?.products ?? data?.data ?? []
    showSuggestions.value = productSuggestions.value.length > 0
  } catch {
    productSuggestions.value = []
    showSuggestions.value = false
  }
}

function onProductFocus() {
  if (form.search && productSuggestions.value.length === 0) {
    searchProducts(form.search).then(() => {
      showSuggestions.value = productSuggestions.value.length > 0
    })
  } else if (productSuggestions.value.length > 0) {
    showSuggestions.value = true
  }
}
function hideSuggestions() {
  setTimeout(() => { showSuggestions.value = false }, 150)
}

function onSearchInput() {
  form.productId = ''
  shipmentInfo.value = null
  showSuggestions.value = false
  if (searchTimeout) clearTimeout(searchTimeout)
  searchTimeout = setTimeout(() => searchProducts(form.search), 300)
}

function selectProduct(p: any) {
  form.productId = String(p.id)
  form.search = p.name
  showSuggestions.value = false
  fetchShipmentInfo()
}

// === 可出货量查询 ===
const shipmentInfo = ref<{ order_quantity: number; shipped_quantity: number; available_quantity: number } | null>(null)

async function fetchShipmentInfo() {
  if (!form.productId || !form.customer) {
    shipmentInfo.value = null
    return
  }
  try {
    const data = await stockApi.availableShipment(Number(form.productId), form.customer) as any
    shipmentInfo.value = data
  } catch {
    shipmentInfo.value = null
  }
}

// === 表单 ===
const today = new Date().toISOString().split('T')[0]
const form = reactive({ customer: '', date: today, search: '', productId: '', quantity: 1, note: '' })

const canAdd = computed(() => {
  if (!form.customer || !form.productId || form.quantity < 1 || !form.date) return false
  return true
})

watch(() => form.customer, () => {
  if (form.productId) fetchShipmentInfo()
})

// === 暂存列表 ===
const staged = ref<any[]>([])

const stagedTotalQty = computed(() => staged.value.reduce((s: number, i: any) => s + (i.quantity || 0), 0))

async function addStaged() {
  if (!canAdd.value) {
    showToast('请选择客户和产品，并输入数量', 'warning')
    return
  }

  if (form.productId && form.customer) {
    try {
      const data = await stockApi.availableShipment(Number(form.productId), form.customer) as any
      if (form.quantity > data.available_quantity) {
        showToast(`出货数量超过可出货量！可出货: ${data.available_quantity}`, 'error')
        return
      }
    } catch { /* proceed anyway */ }
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
  form.search = ''
  form.productId = ''
  form.quantity = 1
  form.note = ''
  shipmentInfo.value = null
}

// === 编辑暂存 ===
const editStagedOpen = ref(false)
const editStagedIdx = ref(-1)
const editStagedForm = reactive({ customer: '', date: '', productName: '', quantity: 1, note: '' })

function openEditStaged(idx: number) {
  editStagedIdx.value = idx
  const item = staged.value[idx]
  editStagedForm.customer = item.customer || ''
  editStagedForm.date = item.date || ''
  editStagedForm.productName = item.productName || ''
  editStagedForm.quantity = item.quantity || 1
  editStagedForm.note = item.note || ''
  editStagedOpen.value = true
}

function saveEditStaged() {
  if (editStagedIdx.value < 0) return
  const item = staged.value[editStagedIdx.value]
  item.customer = editStagedForm.customer
  item.date = editStagedForm.date
  item.quantity = editStagedForm.quantity
  item.note = editStagedForm.note
  editStagedOpen.value = false
}

// === 批量提交 ===
const submitting = ref(false)

async function submitBatch() {
  if (!staged.value.length) return

  submitting.value = true
  try {
    const uniqueKeys: Record<string, { productId: string; customer: string; stockouts: any[] }> = {}
    const withCustomer = staged.value.filter(s => s.customer)
    withCustomer.forEach(s => {
      const key = `${s.productId}-${s.customer}`
      if (!uniqueKeys[key]) uniqueKeys[key] = { productId: s.productId, customer: s.customer, stockouts: [] }
      uniqueKeys[key].stockouts.push(s)
    })

    for (const key in uniqueKeys) {
      const { productId, customer, stockouts } = uniqueKeys[key]
      try {
        const data = await stockApi.availableShipment(Number(productId), customer) as any
        const totalQty = stockouts.reduce((sum: number, s: any) => sum + s.quantity, 0)
        if (totalQty > data.available_quantity) {
          showToast(`客户: ${customer} 产品ID: ${productId} 出货量超过可出货量(${data.available_quantity})`, 'error')
          submitting.value = false
          return
        }
      } catch { /* proceed */ }
    }

    const stockoutsForApi = staged.value.map(s => ({
      product_id: Number(s.productId),
      customer: s.customer,
      quantity: s.quantity,
      stockout_date: s.date,
      note: s.note,
    }))

    const result = await stockApi.batchSubmitStockouts(stockoutsForApi) as any
    if (result.success !== false) {
      showToast('出货提交成功', 'success')
      staged.value = []
      fetchStockouts()
    } else {
      showToast(result.error || result.message || '提交失败', 'error')
    }
  } catch (err: any) {
    showToast(err.response?.data?.detail || '批量提交失败', 'error')
  } finally {
    submitting.value = false
  }
}

// === 批量导入 ===
const showBatchUpload = ref(true)
const excelFile = ref<File | null>(null)
const importing = ref(false)
const templateDownloading = ref(false)
const excelInputRef = ref<HTMLInputElement | null>(null)
const excelDragOver = ref(false)

function onExcelFileSelect(event: Event) {
  const input = event.target as HTMLInputElement
  const f = input.files?.[0]
  if (!f) return
  if (!(f.name.endsWith('.xlsx') || f.name.endsWith('.xls'))) {
    showToast('请上传 Excel 文件（.xlsx 或 .xls）', 'error')
    return
  }
  excelFile.value = f
}

function onExcelDrop(event: DragEvent) {
  excelDragOver.value = false
  const f = event.dataTransfer?.files?.[0]
  if (!f) return
  if (!(f.name.endsWith('.xlsx') || f.name.endsWith('.xls'))) {
    showToast('请上传 Excel 文件（.xlsx 或 .xls）', 'error')
    return
  }
  excelFile.value = f
}

async function handleDownloadTemplate() {
  templateDownloading.value = true
  try {
    await auxApi.downloadTemplate()
  } catch {
    showToast('下载失败', 'error')
  } finally {
    templateDownloading.value = false
  }
}

async function handleImportExcel() {
  if (!excelFile.value) return
  importing.value = true
  try {
    const fd = new FormData()
    fd.append('file', excelFile.value)
    const sessionId = `stg_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
    const res = await stockApi.stagingStockouts.importExcel(fd) as any
    if (res.success) {
      showToast(`成功导入 ${res.imported ?? res.count ?? 0} 条记录到暂存区`, 'success')
      excelFile.value = null
      if (res.data?.length || res.imported) {
        try {
          const confirmRes = await stockApi.stagingStockouts.confirm(sessionId) as any
          if (confirmRes.success) {
            showToast('暂存出货已确认提交', 'success')
            fetchStockouts()
          }
        } catch { /* staging confirm optional */ }
      }
    } else {
      showToast(res.message || '导入失败', 'error')
    }
  } catch (err: any) {
    showToast(err.response?.data?.detail || '导入失败', 'error')
  } finally {
    importing.value = false
  }
}

// === OCR 导入 ===
const showOcrUpload = ref(true)
const pdfFiles = ref<File[]>([])
const ocrPreviewing = ref(false)
const ocrImporting = ref(false)
const ocrProgress = reactive({ show: false, pct: 0, msg: '准备中...' })
const ocrInputRef = ref<HTMLInputElement | null>(null)
const ocrDragOver = ref(false)

function onOcrFileSelect(event: Event) {
  const input = event.target as HTMLInputElement
  pdfFiles.value = input.files ? Array.from(input.files) : []
}

function onOcrDrop(event: DragEvent) {
  ocrDragOver.value = false
  const files = event.dataTransfer?.files
  if (!files) return
  pdfFiles.value = Array.from(files)
}

async function handleOcrPreview() {
  if (!pdfFiles.value.length) return
  ocrPreviewing.value = true
  try {
    const fd = new FormData()
    pdfFiles.value.forEach(f => fd.append('files', f))
    const res = await post('/ocr-import/preview', fd) as any
    showToast(res.message || '预览完成', 'info')
  } catch (err: any) {
    showToast(err.response?.data?.detail || '预览失败', 'error')
  } finally {
    ocrPreviewing.value = false
  }
}

async function handleOcrImport() {
  if (!pdfFiles.value.length) return
  ocrImporting.value = true
  ocrProgress.show = true
  ocrProgress.pct = 0
  ocrProgress.msg = '创建任务...'
  try {
    const task = await ocrApi.createTask() as any
    const taskId = task.task_id || task.id
    if (!taskId) throw new Error('创建OCR任务失败')

    ocrProgress.msg = '上传文件...'
    ocrProgress.pct = 20
    const fd = new FormData()
    pdfFiles.value.forEach(f => fd.append('files', f))
    await ocrApi.upload(taskId, fd)

    ocrProgress.msg = 'OCR识别中...'
    let completed = false
    while (!completed) {
      await new Promise(r => setTimeout(r, 2000))
      const prog = await ocrApi.progress(taskId) as any
      const pct = prog.progress ?? prog.percent ?? 0
      ocrProgress.pct = Math.min(90, 20 + pct * 0.7)
      ocrProgress.msg = prog.status || '处理中...'
      if (prog.status === 'completed' || prog.status === 'done' || prog.progress >= 100) {
        completed = true
      }
    }

    ocrProgress.pct = 100
    ocrProgress.msg = '导入完成'
    showToast('OCR识别导入完成', 'success')
    pdfFiles.value = []
    fetchStockouts()
  } catch (err: any) {
    showToast(err.response?.data?.detail || 'OCR导入失败', 'error')
  } finally {
    ocrImporting.value = false
    setTimeout(() => { ocrProgress.show = false }, 2000)
  }
}

// === 出货记录列表 ===
const showFilter = ref(false)
const filterCustomer = ref('')
const filterStart = ref('')
const filterEnd = ref('')
const currentPage = ref(1)
const totalPages = ref(1)
const isLoading = ref(false)
const stockoutRecords = ref<any[]>([])

async function fetchStockouts() {
  isLoading.value = true
  try {
    const params: Record<string, any> = { page: currentPage.value, per_page: 20 }
    if (filterCustomer.value) params.customer = filterCustomer.value
    if (filterStart.value) params.start_date = filterStart.value
    if (filterEnd.value) params.end_date = filterEnd.value
    const res = await stockApi.stockouts(params) as any
    const items = res.stockouts ?? res.data ?? res.items ?? []
    stockoutRecords.value = items
    const total = res.total ?? items.length
    totalPages.value = Math.ceil(total / 20) || 1
  } catch {
    stockoutRecords.value = []
  } finally {
    isLoading.value = false
  }
}

fetchStockouts()

const groupedRecords = computed(() => {
  const groups: Record<string, any[]> = {}
  stockoutRecords.value.forEach(r => {
    const dateKey = r.stockout_date || '未知日期'
    if (!groups[dateKey]) groups[dateKey] = []
    groups[dateKey].push(r)
  })

  const sortedDates = Object.keys(groups).sort((a, b) => b.localeCompare(a))

  return sortedDates.map(date => {
    const records = groups[date]
    const summaryMap: Record<string, any> = {}
    records.forEach((r: any) => {
      const pid = r.product_id ?? r.product?.id ?? 0
      const key = `${r.customer || '未知客户'}|||${pid}`
      if (!summaryMap[key]) {
        summaryMap[key] = {
          key,
          customer: r.customer || '未知客户',
          productName: r.product_name || r.product?.name || '-',
          productImage: r.product_image || r.product?.image || null,
          barcode: r.barcode || r.product?.barcode || '',
          quantity: 0,
          deductQuantity: 0,
          notes: [] as string[],
          ids: [] as number[],
          firstId: r.id,
        }
      }
      summaryMap[key].quantity += r.quantity || 0
      summaryMap[key].deductQuantity += r.deduct_quantity || 0
      if (r.note && !summaryMap[key].notes.includes(r.note)) summaryMap[key].notes.push(r.note)
      summaryMap[key].ids.push(r.id)
    })

    const summaryList = Object.values(summaryMap).map((item: any) => ({
      ...item,
      notesDisplay: item.notes.length > 0 ? item.notes.join('; ') : '-',
    }))

    return {
      date,
      records,
      summaryList,
      totalQty: summaryList.reduce((s: number, i: any) => s + i.quantity, 0),
      expanded: true,
    }
  })
})

// === 删除出货记录 ===
async function handleDeleteRecord(id: number) {
  if (!(await confirmDialog.confirm('确定要删除该出货记录吗？删除后不可恢复。'))) return
  actionId.value = id
  try {
    await stockApi.deleteStockout(id)
    showToast('删除成功', 'success')
    fetchStockouts()
  } catch (err: any) {
    showToast(err.response?.data?.detail || '删除失败', 'error')
  } finally {
    actionId.value = 0
  }
}

// === 编辑出货记录 ===
const editRecordOpen = ref(false)
const editRecordForm = reactive({ id: 0, customer: '', date: '', productName: '', quantity: 1, note: '' })

function openEditRecord(item: any) {
  editRecordForm.id = item.firstId
  editRecordForm.customer = item.customer || ''
  editRecordForm.date = ''
  editRecordForm.productName = item.productName || ''
  editRecordForm.quantity = item.quantity || 1
  editRecordForm.note = item.notes.length > 0 ? item.notes[0] : ''
  editRecordOpen.value = true
  get(`/stock/out/list`, { id: item.firstId })
    .then((data: any) => {
      const record = Array.isArray(data) ? data[0] : data.stockouts?.[0] ?? data
      if (record) {
        editRecordForm.customer = record.customer || ''
        editRecordForm.date = record.stockout_date || ''
        editRecordForm.productName = record.product_name || record.product?.name || ''
        editRecordForm.quantity = record.quantity || 1
        editRecordForm.note = record.note || ''
      }
    })
    .catch(() => {})
}

async function saveEditRecord() {
  try {
    await put(`/stock/out/edit/${editRecordForm.id}`, {
      customer: editRecordForm.customer,
      stockout_date: editRecordForm.date,
      quantity: editRecordForm.quantity,
      note: editRecordForm.note,
    })
    showToast('更新成功', 'success')
    editRecordOpen.value = false
    fetchStockouts()
  } catch (err: any) {
    showToast(err.response?.data?.detail || '更新失败', 'error')
  }
}
</script>

<style scoped>
/* ===== Form Text Input ===== */
.form-text-input {
  width: 100%;
  padding: 8px 12px;
  border: 2px solid var(--color-border, #cbd5e1);
  border-radius: var(--radius-input, 12px);
  font-size: 14px;
  color: var(--color-text);
  font-family: inherit;
  background: white;
  transition: all 0.3s ease;
  outline: none;
}
.form-text-input:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}

/* ===== Layout ===== */
.stock-out-tab {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.so-tab-content {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.so-body {
  display: grid;
  grid-template-columns: 1fr 1fr;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
@media (max-width: 992px) {
  .so-body { grid-template-columns: 1fr; }
}
.so-col {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
.so-col + .so-col {
  border-left: 2px solid var(--color-border, #cbd5e1);
}
.so-col-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 20px;
  border-bottom: 1px solid var(--color-border, #cbd5e1);
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
}
.so-col-title i {
  color: var(--color-danger-500);
  margin-right: 6px;
  font-size: 13px;
}
.so-col-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 12px 20px;
}

/* ===== Section Header (collapsible) ===== */
.so-section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: white;
  border: 2px solid var(--color-border, #cbd5e1);
  border-radius: var(--radius-input, 12px);
  min-height: 40px;
  box-sizing: border-box;
  cursor: pointer;
  transition: all 0.3s ease;
}
.so-section-header:hover {
  border-color: var(--color-ocean-deep);
  background: var(--color-slate-50);
}
.so-section-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-secondary);
  display: flex;
  align-items: center;
  gap: 6px;
}
.so-section-title i {
  font-size: 13px;
  color: var(--color-danger-500);
}

/* ===== Droppable Label (placeholder style) ===== */
.so-droppable-label {
  display: flex !important;
  margin-bottom: 0;
  cursor: pointer;
  font-size: 14px !important;
  font-weight: 400 !important;
  color: var(--color-text-muted) !important;
}
.so-droppable-label .label-icon {
  color: var(--color-text-muted) !important;
}

/* ===== Section Label ===== */
.so-section-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  padding: 8px 0 4px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.so-section-label i {
  font-size: 12px;
  color: var(--color-text-muted);
}
.so-section-body {
  padding: 8px 0 0;
}
.so-collapsible {
  cursor: pointer;
}
.so-collapse-arrow {
  transition: transform 0.3s;
  color: var(--color-text-secondary);
  font-size: 12px;
}
.so-collapse-arrow.expanded { transform: rotate(180deg); }

/* ===== Records TAB ===== */
.so-records-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 20px;
  border-bottom: 1px solid var(--color-border, #cbd5e1);
}
.so-records-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  display: flex;
  align-items: center;
  gap: 6px;
}
.so-records-title i {
  color: var(--color-danger-500);
}
.so-records-body {
  flex: 1;
  overflow-y: auto;
  padding: 0 20px;
}

/* ===== Form ===== */
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.form-field { margin-bottom: 10px; }
.form-label {
  display: block;
  font-weight: 500;
  font-size: 13px;
  color: var(--color-text-secondary);
  margin-bottom: 4px;
}
.label-icon {
  color: var(--color-danger-500);
  margin-right: 4px;
  font-size: 11px;
}
.form-input {
  width: 100%;
  padding: 8px 12px;
  font-size: 14px;
  line-height: 1.5;
  color: var(--color-text);
  background: white;
  border: 2px solid var(--color-border, #cbd5e1);
  border-radius: var(--radius-input, 12px);
  transition: all 0.3s ease;
  outline: none;
  min-height: 40px;
  box-sizing: border-box;
  font-family: inherit;
  -moz-appearance: textfield;
}
.form-input::-webkit-inner-spin-button,
.form-input::-webkit-outer-spin-button { opacity: 1; }
.form-input:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
textarea.form-input { resize: vertical; }
textarea.form-input::placeholder {
  color: var(--color-text-muted);
  font-size: 14px;
  font-weight: 400;
  opacity: 1;
}
.shipment-info {
  display: block;
  margin-top: 4px;
  color: var(--color-text-secondary);
  font-size: 12px;
}

/* ===== Autocomplete ===== */
.autocomplete-dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  background: white;
  border: 2px solid var(--color-primary-200);
  border-radius: 12px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.12);
  z-index: 1000;
  max-height: 200px;
  overflow-y: auto;
}
.autocomplete-item {
  padding: 10px 14px;
  cursor: pointer;
  transition: all 0.2s ease;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
  display: flex;
  align-items: center;
  font-size: 13px;
}
.autocomplete-item:last-child { border-bottom: none; }
.autocomplete-item:hover {
  background: var(--color-primary-50);
  transform: translateX(4px);
}
.barcode-hint {
  color: var(--color-text-secondary);
  font-size: 12px;
}

/* ===== Staged Cards ===== */
.so-staged-card {
  border: 2px solid var(--color-border, #cbd5e1);
  border-left: 4px solid var(--color-danger-500);
  border-radius: 10px;
  padding: 8px 12px;
  margin-bottom: 6px;
  transition: all 0.3s ease;
}
.so-staged-card:hover {
  border-color: var(--color-primary-300);
  transform: translateY(-1px);
}
.so-staged-main {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.so-staged-info { flex: 1; }
.so-staged-product {
  font-weight: 600;
  margin-bottom: 4px;
  color: var(--color-text);
  font-size: 13px;
}
.so-staged-icon {
  color: var(--color-danger-500);
  margin-right: 4px;
}
.so-staged-meta {
  font-size: 12px;
  color: var(--color-text-secondary);
  margin-bottom: 4px;
  display: flex;
  gap: 8px;
}
.so-staged-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.so-staged-badges { display: flex; gap: 6px; flex-wrap: wrap; }
.so-staged-actions { display: flex; gap: 4px; margin-left: 8px; }
.so-empty-state {
  text-align: center;
  padding: 40px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  color: var(--color-text-secondary);
}
.so-empty-icon {
  font-size: 28px;
  opacity: 0.5;
}
.staged-count {
  color: var(--color-text-secondary);
  font-size: 13px;
  font-weight: 400;
}

/* Staged list transition */
.staged-list-enter-active { transition: all 0.3s ease; }
.staged-list-leave-active { transition: all 0.2s ease; }
.staged-list-enter-from { opacity: 0; transform: translateX(-12px); }
.staged-list-leave-to { opacity: 0; transform: translateX(12px); }
.staged-list-move { transition: transform 0.3s ease; }

/* ===== Badge Tags ===== */
.badge-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
}
.badge-info { background: var(--color-primary-50); color: var(--color-primary-600); }
.badge-danger { background: var(--color-danger-50); color: var(--color-danger-600); }
.badge-success { background: var(--color-success-50); color: var(--color-success-600); }
.badge-secondary { background: var(--color-surface, #f8fafc); color: var(--color-text-secondary); }
.badge-muted { background: var(--color-surface, #f8fafc); color: var(--color-text-muted); }

/* ===== Action Buttons ===== */
.action-group {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
}
.action-btn {
  width: 36px;
  height: 36px;
  border-radius: 9px;
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  transition: all 0.2s ease;
  cursor: pointer;
  padding: 0;
}
.action-edit {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}
.action-edit:hover {
  background: var(--color-primary-100);
  transform: translateY(-1px);
}
.action-delete {
  background: var(--color-danger-50);
  color: var(--color-danger-500);
}
.action-delete:hover {
  background: var(--color-danger-100);
  transform: translateY(-1px);
}
.action-delete:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* ===== Submit Bar ===== */
.so-submit-bar {
  display: flex;
  justify-content: center;
  padding: 8px 0;
  border-top: 1px solid var(--color-border, #cbd5e1);
}

/* ===== Droppable Section Header ===== */
.so-droppable {
  cursor: pointer;
}
.so-droppable.so-drag-over {
  border-color: var(--color-success-400);
  background: var(--color-success-50);
}
.so-droppable-danger.so-drag-over {
  border-color: var(--color-danger-400);
  background: var(--color-danger-50);
}
.so-upload-icon-inline {
  font-size: 14px;
  color: var(--color-success-500);
  margin-right: 2px;
}
.so-upload-icon-danger {
  color: var(--color-danger-500);
}
.so-file-inline {
  font-size: 12px;
  font-weight: 400;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.so-file-inline-success {
  color: var(--color-success-700);
}
.so-file-inline-danger {
  color: var(--color-danger-700);
}
.so-section-body-compact {
  padding: 2px 12px 4px;
}
.so-upload-hint-inline {
  font-size: 11px;
  color: var(--color-text-muted);
}

/* ===== Inline Actions (in section header) ===== */
.so-inline-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}
.so-inline-btn {
  padding: 3px 8px;
  border: 1px solid var(--color-border, #cbd5e1);
  border-radius: 6px;
  background: white;
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: all 0.2s ease;
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
.so-inline-btn:hover:not(:disabled) {
  border-color: var(--color-primary-300);
  color: var(--color-primary-600);
  transform: translateY(-1px);
}
.so-inline-btn-success:hover:not(:disabled) {
  border-color: var(--color-success-300);
  color: var(--color-success-600);
}
.so-inline-btn-danger:hover:not(:disabled) {
  border-color: var(--color-danger-300);
  color: var(--color-danger-600);
}
.so-inline-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* ===== OCR Progress ===== */
.ocr-progress { margin-top: 12px; }
.ocr-progress-bar {
  height: 8px;
  border-radius: 4px;
  background: var(--color-danger-50);
  overflow: hidden;
}
.ocr-progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--color-danger-400), var(--color-danger-600));
  transition: width 0.3s ease;
  border-radius: 4px;
}
.ocr-progress-text {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 4px;
  color: var(--color-text-secondary);
  font-size: 12px;
}

/* ===== Filter ===== */
.filter-panel {
  padding: 14px 16px;
  background: var(--color-surface, #f8fafc);
  border-bottom: 1px solid var(--color-border-light);
  margin-bottom: 0;
}
.filter-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: flex-end;
}
.filter-field { flex: 1; min-width: 140px; }
.filter-action { flex: 0 0 auto; }

/* ===== Date Groups ===== */
.date-group {
  margin-bottom: 0;
  border-bottom: 1px solid var(--color-border-light);
}
.date-group:last-child { border-bottom: none; }
.date-group-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  background: transparent;
  cursor: pointer;
  transition: background 0.2s ease;
}
.date-group-header:hover {
  background: var(--color-primary-50);
}
.date-group-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
}
.date-group-title i {
  color: var(--color-danger-500);
}
.toggle-icon {
  transition: transform 0.3s;
  color: var(--color-text-secondary);
  font-size: 12px;
}
.toggle-icon.expanded { transform: rotate(180deg); }
.date-group-content {
  padding: 0;
}

/* Group expand transition */
.group-expand-enter-active { transition: all 0.3s ease; }
.group-expand-leave-active { transition: all 0.2s ease; }
.group-expand-enter-from,
.group-expand-leave-to { max-height: 0; opacity: 0; overflow: hidden; }
.group-expand-enter-to,
.group-expand-leave-from { max-height: 2000px; opacity: 1; }

/* ===== Table ===== */
.so-table {
  width: 100%;
  border-collapse: collapse;
}
.so-table thead th {
  padding: 10px 14px;
  font-weight: 600;
  font-size: 12px;
  color: var(--color-text);
  border-bottom: 2px solid var(--color-border-light, #e2e8f0);
  line-height: 1.5;
  background: var(--color-surface, #f8fafc);
  text-align: center;
}
.so-table tbody tr {
  transition: background 0.2s ease;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
}

.so-table tbody tr:hover {
  background: var(--color-primary-50);
}
.so-table tbody td {
  padding: 10px 14px;
  vertical-align: middle;
  font-size: 13px;
  color: var(--color-text);
  line-height: 1.5;
  text-align: center;
}
.product-thumb {
  width: 36px;
  height: 36px;
  object-fit: cover;
  border-radius: 6px;
}
.cell-main {
  font-weight: 500;
  color: var(--color-text);
}
.cell-muted {
  font-size: 12px;
  color: var(--color-text-secondary);
}

/* ===== Empty & Loading ===== */
.state-placeholder {
  padding: 40px 20px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}
.state-empty {
  padding: 60px 20px;
}
.empty-illustration {
  font-size: 28px;
  opacity: 0.5;
  color: var(--color-danger-500);
}
.state-text {
  font-size: 14px;
  color: var(--color-text-secondary);
  margin: 0;
}
.spinner-ring {
  width: 36px;
  height: 36px;
  border: 3px solid var(--color-border-light);
  border-top-color: var(--color-danger-500);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
.pagination-wrap {
  padding: 12px 16px;
  border-top: 1px solid var(--color-border-light);
}

/* ===== Dialog Form ===== */
.dialog-form {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

/* ===== Animations ===== */
@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ===== Responsive ===== */
@media (max-width: 767.98px) {
  .form-grid { grid-template-columns: 1fr; }
  .so-table thead th,
  .so-table tbody td {
    padding: 8px 10px;
    font-size: 12px;
  }
}
</style>
