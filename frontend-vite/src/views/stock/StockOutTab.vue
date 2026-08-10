<template>
  <div class="stock-out-tab">
    <!-- TAB: 录入 -->
    <div v-show="activeTab === 'input'" class="so-tab-content">
      <div class="so-body">
        <!-- 左栏：出货信息录入 -->
        <div class="so-col">
          <div class="so-col-title">
            <span>出货信息录入</span>
            <UiBadge v-if="staged.length" variant="cancelled">已暂存: {{ staged.length }}</UiBadge>
          </div>
          <div class="so-col-scroll">
            <form @submit.prevent>
              <div class="form-grid">
                <div class="form-field">
                  <label class="form-label">订单类型 <span style="color: var(--color-danger-500)">*</span></label>
                  <UiSelect v-model="form.orderType" placeholder="请选择订单类型" :options="orderTypeOptions" />
                </div>
                <div v-if="form.orderType === 'custom'" class="form-field">
                  <label class="form-label">国家 <span style="color: var(--color-danger-500)">*</span></label>
                  <UiSelect v-model="form.country" placeholder="请选择国家" :options="countryStore.countryOptions" />
                </div>
              </div>

              <div class="form-grid">
                <div class="form-field">
                  <label class="form-label">出货时间</label>
                  <UiDatePicker v-model="form.date" style="width: 100%" />
                </div>
                <div class="form-field">
                  <label class="form-label">客户名称</label>
                  <UiSelect v-model="form.customer" placeholder="请选择客户" :options="customerOptions" />
                </div>
              </div>

              <div class="form-field">
                <label class="form-label">产品名称</label>
                <UiAutocomplete
                  v-model="form.search"
                  :searchFn="searchProductsForAutocomplete"
                  placeholder="输入产品名称或69码搜索"
                  @select="onProductSelect"
                  @update:modelValue="form.productId = ''; shipmentInfo = null"
                >
                  <template #option="{ item }">
                    {{ item.name }}
                  </template>
                </UiAutocomplete>
              </div>

              <div class="form-field">
                <label class="form-label">出货数量</label>
                <input type="number" class="form-input" v-model.number="form.quantity" min="1" step="1" name="quantity" autocomplete="off" />
                <small v-if="shipmentInfo" class="shipment-info">
                  <FontAwesomeIcon icon="info-circle" style="margin-right: 4px"  aria-hidden="true" />
                  订单量: {{ shipmentInfo.order_quantity }} | 已出货: {{ shipmentInfo.shipped_quantity }} | 可出货:
                  <strong style="color: var(--color-primary-500)">{{ shipmentInfo.available_quantity }}</strong>
                  <template v-if="shipmentInfo.regular_available != null || shipmentInfo.custom_available != null">
                    <span class="shipment-detail">（常规: {{ shipmentInfo.regular_available ?? 0 }} | 定制: {{ shipmentInfo.custom_available ?? 0 }}）</span>
                  </template>
                </small>
              </div>

              <div class="form-field">
                <label class="form-label">备注</label>
                <textarea
                  v-model="form.note"
                  class="form-input"
                  rows="2"
                  placeholder="例如：物流发货"
                />
              </div>

              <!-- 批量导入出货 -->
              <div class="so-section-label"><FontAwesomeIcon icon="file-import" aria-hidden="true" /> 批量导入</div>
              <div
                class="so-section-header so-droppable"
                :class="{ 'so-drag-over': excelDragOver }"
                @click="excelInputRef?.click()"
                @dragover.prevent="excelDragOver = true"
                @dragleave="excelDragOver = false"
                @drop.prevent="onExcelDrop"
              >
                <label class="form-label so-droppable-label">
                  <FontAwesomeIcon icon="file-excel" class="label-icon" aria-hidden="true" />
                  <span v-if="excelFile" class="so-file-inline so-file-inline-success"><FontAwesomeIcon icon="file-excel" aria-hidden="true" />{{ excelFile.name }}</span>
                  <span v-else>拖拽文件到标题栏 · 支持 .xlsx / .xls</span>
                </label>
                <div class="so-inline-actions">
                  <button class="so-inline-btn" :disabled="templateDownloading" @click.stop="handleDownloadTemplate">
                    <UiLoadingIcon :loading="templateDownloading" icon="download" />模板
                  </button>
                  <button class="so-inline-btn so-inline-btn-success" :disabled="!excelFile || importing" @click.stop="handleImportExcel">
                    <UiLoadingIcon :loading="importing" icon="upload" />{{
                      importing ? '导入中' : '导入'
                    }}
                  </button>
                </div>
                <input
                  ref="excelInputRef"
                  type="file"
                  accept=".xlsx,.xls"
                  name="file"
                  style="display: none"
                  @change="onExcelFileSelect"
                />
              </div>

              <!-- OCR 识别 -->
              <div class="so-section-label"><FontAwesomeIcon icon="file-pdf" aria-hidden="true" /> OCR 识别</div>
              <div
                class="so-section-header so-droppable so-droppable-danger"
                :class="{ 'so-drag-over': ocrDragOver }"
                @click="ocrInputRef?.click()"
                @dragover.prevent="ocrDragOver = true"
                @dragleave="ocrDragOver = false"
                @drop.prevent="onOcrDrop"
              >
                <label class="form-label so-droppable-label">
                  <FontAwesomeIcon icon="file-pdf" class="label-icon" aria-hidden="true" />
                  <span v-if="pdfFiles.length" class="so-file-inline so-file-inline-danger"><FontAwesomeIcon icon="file-image" aria-hidden="true" />已选 {{ pdfFiles.length }} 个文件</span>
                  <span v-else>拖拽文件到标题栏 · 支持 PDF / PNG / JPG / BMP / TIFF</span>
                </label>
                <div class="so-inline-actions">
                  <button class="so-inline-btn" :disabled="!pdfFiles.length || ocrPreviewing" @click.stop="handleOcrPreview">
                    <UiLoadingIcon :loading="ocrPreviewing" icon="eye" />预览
                  </button>
                  <button class="so-inline-btn so-inline-btn-danger" :disabled="!pdfFiles.length || ocrImporting" @click.stop="handleOcrImport">
                    <UiLoadingIcon :loading="ocrImporting" icon="magic" />导入
                  </button>
                </div>
                <input
                  ref="ocrInputRef"
                  type="file"
                  accept=".pdf,.png,.jpg,.jpeg,.bmp,.tiff,.tif,.webp"
                  multiple
                  name="file"
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
                <FontAwesomeIcon icon="plus-circle" aria-hidden="true" />新增出货
              </UiButton>
            </form>
          </div>
        </div>

        <!-- 右栏：暂存列表 -->
        <div class="so-col">
          <div class="so-col-title">
            <span><FontAwesomeIcon icon="clipboard-list" aria-hidden="true" /> 暂存出货列表</span>
            <span class="staged-count">共 {{ staged.length }} 个，合计 {{ stagedTotalQty }}</span>
          </div>
          <div class="so-col-scroll">
            <div v-if="staged.length === 0" class="so-empty-state">
              <FontAwesomeIcon icon="box-open" class="so-empty-icon" aria-hidden="true" />
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
                      <FontAwesomeIcon icon="shipping-fast" class="so-staged-icon" aria-hidden="true" />{{ item.product_name }}
                    </div>
                    <div class="so-staged-meta">
                      <span class="so-staged-tag"><FontAwesomeIcon icon="user" aria-hidden="true" />{{ item.customer || '无客户' }}</span>
                      <span class="so-staged-tag"><FontAwesomeIcon icon="calendar-alt" aria-hidden="true" />{{ item.date }}</span>
                    </div>
                    <div class="so-staged-badges">
                      <span class="badge-tag badge-danger">数量: {{ item.quantity }}</span>
                      <span v-if="item.order_type === 'custom'" class="badge-tag badge-warning">定制{{ item.country ? `·${item.country}` : '' }}</span>
                      <span v-if="item.note" class="badge-tag badge-secondary">备注: {{ item.note }}</span>
                    </div>
                  </div>
                  <div class="so-staged-actions">
                    <button class="action-btn action-edit" @click="openEditStaged(idx)" aria-label="编辑">
                      <FontAwesomeIcon icon="edit" aria-hidden="true" />
                    </button>
                    <button class="action-btn action-delete" @click="removeStagedItem(idx)" aria-label="删除">
                      <FontAwesomeIcon icon="trash" aria-hidden="true" />
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
          <FontAwesomeIcon icon="paper-plane" style="margin-right: 6px"  aria-hidden="true" />
          {{ submitting ? '提交中…' : '添加出货' }}
        </UiButton>
      </div>
    </div>

    <!-- TAB: 记录查询 -->
    <div v-show="activeTab === 'records'" class="so-tab-content">
      <div class="so-records-header">
        <span class="so-records-title"><FontAwesomeIcon icon="list-alt" aria-hidden="true" /> 出货记录列表</span>
        <UiButton variant="outline" size="sm" @click="showFilter = !showFilter">
          <FontAwesomeIcon icon="filter" style="margin-right: 4px"  aria-hidden="true" />筛选
        </UiButton>
      </div>

      <div v-if="showFilter" class="so-filter-panel">
        <div class="so-filter-row">
          <div class="so-filter-field">
            <label class="so-label"><FontAwesomeIcon icon="user" aria-hidden="true" /> 客户</label>
            <UiSelect v-model="filterCustomer" placeholder="全部" :options="customerOptions" style="width: 100%" />
          </div>
          <div class="so-filter-field">
            <label class="so-label"><FontAwesomeIcon icon="tag" aria-hidden="true" /> 订单类型</label>
            <UiSelect v-model="filterOrderType" placeholder="全部" :options="filterOrderTypeOptions" style="width: 100%" />
          </div>
          <div class="so-filter-field" style="grid-column: span 2">
            <label class="so-label"><FontAwesomeIcon icon="calendar-alt" aria-hidden="true" /> 日期范围</label>
            <UiDateRangePicker v-model="filterDateRange" style="width: 100%" />
          </div>
          <div class="so-filter-field so-filter-action">
            <UiButton variant="primary" size="sm" @click="fetchStockouts">
              <FontAwesomeIcon icon="search" style="margin-right: 4px"  aria-hidden="true" />查询
            </UiButton>
            <UiButton variant="outline" size="sm" @click="resetFilter">
              <FontAwesomeIcon icon="undo" style="margin-right: 4px"  aria-hidden="true" />重置
            </UiButton>
          </div>
        </div>
      </div>

      <div class="so-records-body">
        <div v-if="isLoading && stockoutRecords.length === 0" class="so-state-placeholder">
          <div class="so-spinner-ring" />
          <p class="so-state-text">加载中…</p>
        </div>
        <div v-else-if="stockoutRecords.length === 0" class="so-state-placeholder so-state-empty">
          <div class="so-empty-illustration"><FontAwesomeIcon icon="shipping-fast" aria-hidden="true" /></div>
          <p class="so-state-text">暂无出货记录</p>
        </div>

        <template v-else>
          <div v-if="isFetching" class="so-fetching-bar"><div class="so-fetching-progress" /></div>
          <table class="so-table">
            <thead>
              <tr>
                <th>出货时间</th>
                <th>客户</th>
                <th>产品</th>
                <th>数量</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in stockoutRecords" :key="item.id">
                <td><span class="so-cell-muted">{{ item.stockout_date }}</span></td>
                <td><span class="so-cell-main">{{ item.customer || '-' }}</span></td>
                <td style="text-align: center">
                  <span class="so-cell-main">{{ item.product_name || item.product?.name || '-' }}</span>
                  <span v-if="item.barcode || item.product?.barcode" class="so-cell-muted" style="display: block; font-size: 11px;">{{ item.barcode || item.product?.barcode }}</span>
                </td>
                <td><strong>{{ item.quantity }}</strong></td>
                <td>
                  <div class="so-action-group">
                    <button class="so-btn-icon so-btn-info" @click="openDetail(item)" aria-label="详情">
                      <FontAwesomeIcon icon="eye" aria-hidden="true" />
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </template>

        <UiPagination v-if="totalPages > 1" :current-page="currentPage" :total-pages="totalPages" @update:current-page="currentPage = $event; fetchStockouts()" />
      </div>
    </div>

    <!-- 出货详情弹窗 -->
    <UiDialog v-model:open="detailOpen" title="出货详情" max-width-class="max-w-[500px]">
      <div v-if="detailData" class="so-detail-dialog">
        <div class="so-detail-grid">
          <div class="so-detail-cell">
            <span class="so-detail-label">出货时间</span>
            <span class="so-detail-value">{{ detailData.stockout_date || '-' }}</span>
          </div>
          <div class="so-detail-cell">
            <span class="so-detail-label">客户</span>
            <span class="so-detail-value">{{ detailData.customer || '-' }}</span>
          </div>
          <div class="so-detail-cell">
            <span class="so-detail-label">产品</span>
            <span class="so-detail-value">{{ detailData.product_name || detailData.product?.name || '-' }}</span>
          </div>
          <div class="so-detail-cell">
            <span class="so-detail-label">69码</span>
            <span class="so-detail-value so-detail-mono">{{ detailData.barcode || detailData.product?.barcode || '-' }}</span>
          </div>
          <div class="so-detail-cell">
            <span class="so-detail-label">数量</span>
            <span class="so-detail-value"><strong>{{ detailData.quantity }}</strong></span>
          </div>
          <div class="so-detail-cell">
            <span class="so-detail-label">抵扣备货</span>
            <span class="so-detail-value">{{ detailData.deduct_quantity > 0 ? `抵扣: ${detailData.deduct_quantity}` : '否' }}</span>
          </div>
          <div class="so-detail-cell">
            <span class="so-detail-label">订单类型</span>
            <span class="so-detail-value">{{ detailData.order_type === 'custom' ? '定制' : '常规' }}</span>
          </div>
          <div v-if="detailData.country" class="so-detail-cell">
            <span class="so-detail-label">国家</span>
            <span class="so-detail-value">{{ detailData.country }}</span>
          </div>
        </div>
        <div v-if="detailData.note" class="so-detail-note">
          <span class="so-detail-label">备注</span>
          <span class="so-detail-value">{{ detailData.note }}</span>
        </div>
      </div>
      <template #footer>
        <UiButton variant="outline" @click="detailOpen = false">关闭</UiButton>
      </template>
    </UiDialog>

    <!-- 编辑暂存出货弹窗 -->
    <UiDialog v-model:open="editStagedOpen" title="编辑暂存出货" max-width-class="max-w-[500px]">
      <div class="dialog-form">
        <div class="form-field">
          <label class="form-label">出货时间</label>
          <UiDatePicker v-model="editStagedForm.date" style="width: 100%" />
        </div>
        <div class="form-field">
          <label class="form-label">客户名称</label>
          <UiSelect v-model="editStagedForm.customer" :options="customerOptions" />
        </div>
        <div class="form-field">
          <label class="form-label">产品名称</label>
          <UiInput :model-value="editStagedForm.productName" disabled />
        </div>
        <div class="form-field">
          <label class="form-label">出货数量</label>
          <input type="number" class="form-input" v-model.number="editStagedForm.quantity" min="1" step="1" name="quantity" autocomplete="off" />
        </div>
        <div class="form-field">
          <label class="form-label">订单类型</label>
          <UiSelect v-model="editStagedForm.orderType" :options="orderTypeOptions" />
        </div>
        <div v-if="editStagedForm.orderType === 'custom'" class="form-field">
          <label class="form-label">国家 <span style="color: var(--color-danger-500)">*</span></label>
          <UiSelect v-model="editStagedForm.country" placeholder="请选择国家" :options="countryStore.countryOptions" />
        </div>
        <div class="form-field">
          <label class="form-label">备注</label>
          <textarea v-model="editStagedForm.note" class="form-input" rows="2" />
        </div>
      </div>
      <template #footer>
        <UiButton variant="outline" @click="editStagedOpen = false">取消</UiButton>
        <UiButton variant="primary" @click="saveEditStaged">保存</UiButton>
      </template>
    </UiDialog>

    <UiDialog :open="stockWarningOpen" title="库存不足提示" max-width-class="max-w-[480px]" @update:open="stockWarningOpen = $event">
      <div class="so-stock-warning">
        <div class="so-stock-warning-icon">
          <FontAwesomeIcon icon="exclamation-triangle" aria-hidden="true" />
        </div>
        <p class="so-stock-warning-title">该国家定制库存不足以完成出库</p>
        <div class="so-stock-warning-detail">
          <div class="so-stock-warning-row">
            <span class="so-stock-warning-label">产品</span>
            <span class="so-stock-warning-value">{{ stockWarningData.productName }}</span>
          </div>
          <div class="so-stock-warning-row">
            <span class="so-stock-warning-label">国家</span>
            <span class="so-stock-warning-value">{{ stockWarningData.country }}</span>
          </div>
          <div class="so-stock-warning-row">
            <span class="so-stock-warning-label">该国家可用库存</span>
            <span class="so-stock-warning-value so-stock-warning-num">{{ stockWarningData.availableStock }}</span>
          </div>
          <div class="so-stock-warning-row">
            <span class="so-stock-warning-label">出库需求数量</span>
            <span class="so-stock-warning-value so-stock-warning-num so-stock-warning-demand">{{ stockWarningData.demandQty }}</span>
          </div>
        </div>
      </div>
      <template #footer>
        <UiButton variant="primary" @click="stockWarningOpen = false">知道了</UiButton>
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
import { ref, reactive, computed, onUnmounted, watch } from 'vue'
import { useQueryClient, useQuery } from '@tanstack/vue-query'
import { customerApi, stockApi, auxApi } from '@/api'
import { useCountryStore } from '@/stores/country'
import type { ApiResponse, ShipmentInfo, StagedStockout, Product } from '@/types'
import { useOcrImport } from './composables/useOcrImport'
import { useStockWarning } from './composables/useStockWarning'
import { useStockOutActions } from './composables/useStockOutActions'

const props = defineProps<{ activeTab: 'input' | 'records' }>()
import UiInput from '@/components/ui/UiInput.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { showToast } from '@/composables/useToast'

const countryStore = useCountryStore()
if (!countryStore.loaded) {
  countryStore.fetchCountries()
}
import { toISODate } from '@/utils/format'

const queryClient = useQueryClient()
const confirmDialog = useConfirmDialog()

// === 库存不足弹窗（逻辑抽离至 useStockWarning composable） ===
const { stockWarningOpen, stockWarningData, checkCountryStock } = useStockWarning()

// === 客户列表 ===

const { data: namesData } = useQuery({
  queryKey: ['customer-active-names'],
  queryFn: async () => { const res = await customerApi.activeNames(); return res ?? [] },
  staleTime: 30_000,
})
const customerNames = computed(() => {
  const arr = Array.isArray(namesData.value) ? namesData.value : []
  return arr.map((entry: unknown) => (typeof entry === 'object' && entry !== null ? (entry as { name?: string }).name : entry))
})
const customerOptions = computed(() => customerNames.value.map((name: unknown) => ({ value: String(name), label: String(name) })))

// === 产品搜索 ===
async function searchProductsForAutocomplete(q: string): Promise<Product[]> {
  if (!q.trim()) return []
  try {
    const data = await stockApi.searchProducts(q)
    return Array.isArray(data) ? data : (data?.products ? [data.products] : [])
  } catch {
    return []
  }
}

function onProductSelect(product: Product) {
  form.productId = String(product.id)
  form.search = product.name
  fetchShipmentInfo()
}

// === 可出货量查询 ===
const shipmentInfo = ref<ShipmentInfo | null>(null)

async function fetchShipmentInfo() {
  if (!form.productId || !form.customer) {
    shipmentInfo.value = null
    return
  }
  try {
    const orderType = form.orderType || undefined
    const country = form.orderType === 'custom' && form.country ? form.country : undefined
    const data = await stockApi.availableShipment(Number(form.productId), form.customer, orderType, country)
    shipmentInfo.value = data.data ?? null
  } catch {
    shipmentInfo.value = null
  }
}

// === 表单 ===
const today = toISODate()
const form = reactive({ customer: '', date: today, search: '', productId: '', quantity: 0, note: '', orderType: 'regular', country: '' })

const orderTypeOptions = [
  { value: 'regular', label: '常规订单' },
  { value: 'custom', label: '定制订单' },
]

const canAdd = computed(() => {
  if (!form.customer || !form.productId || form.quantity < 1 || !form.date) return false
  if (form.orderType === 'custom' && !form.country.trim()) return false
  return true
})

watch(() => form.customer, () => {
  if (form.productId) fetchShipmentInfo()
})

watch(() => form.orderType, () => {
  if (form.productId && form.customer) fetchShipmentInfo()
})

watch(() => form.country, () => {
  if (form.orderType === 'custom' && form.productId && form.customer) fetchShipmentInfo()
})

// === 暂存列表 ===
const staged = ref<StagedStockout[]>([])

async function removeStagedItem(idx: number) {
  const ok = await confirmDialog.confirm('确定删除？', '此操作不可恢复', 'danger')
  if (!ok) return
  staged.value.splice(idx, 1)
}

const stagedTotalQty = computed(() => staged.value.reduce((sum: number, item: StagedStockout) => sum + (item.quantity || 0), 0))

async function addStaged() {
  if (!canAdd.value) {
    showToast('请选择客户和产品，并输入数量', 'warning')
    return
  }

  if (form.productId && form.customer) {
    if (shipmentInfo.value === null) {
      await fetchShipmentInfo()
    }
    const avail = shipmentInfo.value?.available_quantity
    if (avail !== undefined && form.quantity > avail) {
      showToast(`出货数量超过可出货量！可出货: ${avail}`, 'error')
      return
    }
  }

  // 定制订单：校验该国家该SKU的库存是否充足
  if (form.orderType === 'custom' && form.country && form.productId) {
    const stockOk = await checkCountryStock(form.search, form.productId, form.country, form.quantity)
    if (!stockOk) return
  }

  staged.value.push({
    id: Date.now(),
    product_id: form.productId,
    product_name: form.search,
    customer: form.customer,
    date: form.date,
    quantity: form.quantity,
    note: form.note,
    order_type: form.orderType,
    country: form.orderType === 'custom' ? form.country : '',
  })
  form.search = ''
  form.productId = ''
  form.quantity = 0
  form.note = ''
  form.orderType = 'regular'
  form.country = ''
  shipmentInfo.value = null
}

// === 编辑暂存 ===
const editStagedOpen = ref(false)
const editStagedIdx = ref(-1)
const editStagedForm = reactive({ customer: '', date: '', productName: '', quantity: 1, note: '', orderType: 'regular', country: '' })

function openEditStaged(idx: number) {
  editStagedIdx.value = idx
  const item = staged.value[idx]
  editStagedForm.customer = item.customer || ''
  editStagedForm.date = item.date || ''
  editStagedForm.productName = item.product_name || ''
  editStagedForm.quantity = item.quantity || 1
  editStagedForm.note = item.note || ''
  editStagedForm.orderType = item.order_type || 'regular'
  editStagedForm.country = item.country || ''
  editStagedOpen.value = true
}

function saveEditStaged() {
  if (editStagedIdx.value < 0) return
  const item = staged.value[editStagedIdx.value]
  item.customer = editStagedForm.customer
  item.date = editStagedForm.date
  item.quantity = editStagedForm.quantity
  item.note = editStagedForm.note
  item.order_type = editStagedForm.orderType
  item.country = editStagedForm.orderType === 'custom' ? editStagedForm.country : ''
  editStagedOpen.value = false
}

// === 批量提交 ===
const submitting = ref(false)

const { submitBatch } = useStockOutActions(staged, submitting, () => {
  fetchStockouts()
  queryClient.invalidateQueries({ queryKey: ['pp-monthly'] })
  queryClient.invalidateQueries({ queryKey: ['pp-summary'] })
})

// === 批量导入 ===
const excelFile = ref<File | null>(null)
const importing = ref(false)
const templateDownloading = ref(false)
const excelInputRef = ref<HTMLInputElement | null>(null)
const excelDragOver = ref(false)

function onExcelFileSelect(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  if (!(file.name.endsWith('.xlsx') || file.name.endsWith('.xls'))) {
    showToast('请上传 Excel 文件（.xlsx 或 .xls）', 'error')
    return
  }
  excelFile.value = file
}

function onExcelDrop(event: DragEvent) {
  excelDragOver.value = false
  const file = event.dataTransfer?.files?.[0]
  if (!file) return
  if (!(file.name.endsWith('.xlsx') || file.name.endsWith('.xls'))) {
    showToast('请上传 Excel 文件（.xlsx 或 .xls）', 'error')
    return
  }
  excelFile.value = file
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
    const res = await stockApi.stagingStockouts.importExcel(fd, sessionId)
    if (res.success) {
      showToast(`成功导入 ${res.imported ?? 0} 条记录到暂存区`, 'success')
      excelFile.value = null
      if (res.imported) {
        try {
          const confirmRes = await stockApi.stagingStockouts.confirm(sessionId) as ApiResponse
          if (confirmRes.success) {
            showToast('暂存出货已确认提交', 'success')
            fetchStockouts()
            queryClient.invalidateQueries({ queryKey: ['pp-monthly'] })
            queryClient.invalidateQueries({ queryKey: ['pp-summary'] })
          }
        } catch { /* staging confirm optional */ }
      }
    } else {
      showToast(res.message || '导入失败', 'error')
    }
  } catch (err: unknown) {
    const error = err as { response?: { data?: { detail?: string } } }
    showToast(error.response?.data?.detail || '导入失败', 'error')
  } finally {
    importing.value = false
  }
}

// === OCR 导入 (composable) ===
const {
  pdfFiles, ocrPreviewing, ocrImporting, ocrProgress, ocrInputRef, ocrDragOver,
  onOcrFileSelect, onOcrDrop, handleOcrPreview, handleOcrImport,
} = useOcrImport(() => {
  fetchStockouts()
  queryClient.invalidateQueries({ queryKey: ['pp-monthly'] })
  queryClient.invalidateQueries({ queryKey: ['pp-summary'] })
})

// === 出货记录列表 ===
const showFilter = ref(false)
const filterCustomer = ref('')
const filterOrderType = ref('')
const filterStart = ref('')
const filterEnd = ref('')
const filterDateRange = computed<[string, string] | null>({
  get: () => (filterStart.value && filterEnd.value ? [filterStart.value, filterEnd.value] : null),
  set: (val) => {
    if (val && val.length === 2) {
      filterStart.value = val[0]
      filterEnd.value = val[1]
    } else {
      filterStart.value = ''
      filterEnd.value = ''
    }
    fetchStockouts()
  },
})
const currentPage = ref(1)
const totalPages = ref(1)
const isLoading = ref(false)
const isFetching = ref(false)
const stockoutRecords = ref<{
  id?: number;
  stockout_date?: string;
  product_id?: number;
  product?: { id?: number; name?: string; image?: string; barcode?: string };
  product_name?: string;
  product_image?: string;
  barcode?: string;
  customer?: string;
  quantity?: number;
  deduct_quantity?: number;
  note?: string;
  order_type?: string;
  country?: string;
}[]>([])

const filterOrderTypeOptions = [
  { value: 'regular', label: '常规订单' },
  { value: 'custom', label: '定制订单' },
]

async function fetchStockouts() {
  const isInitial = stockoutRecords.value.length === 0
  if (isInitial) isLoading.value = true
  else isFetching.value = true
  try {
    const params: Record<string, unknown> = { page: currentPage.value, per_page: 20 }
    if (filterCustomer.value) params.customer = filterCustomer.value
    if (filterOrderType.value) params.order_type = filterOrderType.value
    if (filterStart.value) params.start_date = filterStart.value
    if (filterEnd.value) params.end_date = filterEnd.value
    const res = await stockApi.stockouts(params)
    const items = res.stockouts ?? res.items ?? (Array.isArray(res.data) ? res.data : []) ?? []
    stockoutRecords.value = items as typeof stockoutRecords.value
    const total = res.total ?? items.length
    totalPages.value = Math.ceil(total / 20) || 1
  } catch {
    stockoutRecords.value = []
  } finally {
    isLoading.value = false
    isFetching.value = false
  }
}

function resetFilter() {
  filterCustomer.value = ''
  filterOrderType.value = ''
  filterStart.value = ''
  filterEnd.value = ''
  currentPage.value = 1
  fetchStockouts()
}

// 切换到记录查询tab时自动加载数据（首次进入时触发）
watch(() => props.activeTab, (tab) => {
  if (tab === 'records' && stockoutRecords.value.length === 0) {
    fetchStockouts()
  }
})

// === 详情弹窗 ===
const detailOpen = ref(false)
const detailData = ref<(typeof stockoutRecords.value)[number] | null>(null)

function openDetail(item: (typeof stockoutRecords.value)[number]) {
  detailData.value = item
  detailOpen.value = true
}
</script>

<style scoped>
/* ===== 强制覆盖产品名称输入框灰色背景（PT HMR 不重载 main.ts 的双保险） ===== */
:deep(input.bg-slate-50) {
  background-color: #ffffff !important;
}

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
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
  outline: none;
}
.form-text-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
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
  transition: border-color 0.3s ease, background 0.3s ease;
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
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  border-bottom: 1px solid var(--color-border, #cbd5e1);
  flex-shrink: 0;
}
.so-records-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  display: flex;
  align-items: center;
  gap: 8px;
}
.so-records-title i {
  color: var(--color-danger-500);
}
.so-records-body {
  flex: 1;
  overflow-y: auto;
  padding: 0;
  min-height: 0;
}

/* ===== Filter Panel ===== */
.so-filter-panel {
  padding: 12px 20px;
  border-bottom: 1px solid var(--color-border, #cbd5e1);
  background: var(--color-surface, #f8fafc);
}
.so-filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: flex-end;
}
.so-filter-field {
  min-width: 140px;
  flex: 1;
}
.so-filter-field .so-label {
  font-size: 12px;
  margin-bottom: 4px;
}
.so-filter-action {
  display: flex;
  gap: 8px;
  flex: 0 0 auto;
  min-width: auto;
}
.so-label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 4px;
  color: var(--color-text-secondary);
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
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
  outline: none;
  min-height: 40px;
  box-sizing: border-box;
  font-family: inherit;
  -moz-appearance: textfield;
}
.form-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
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
.shipment-detail {
  margin-left: 4px;
  color: var(--color-text-tertiary);
  font-size: 11px;
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
  transition: background 0.2s ease, transform 0.2s ease;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
  display: flex;
  align-items: center;
  font-size: 13px;
}
.autocomplete-item:last-child { border-bottom: none; }
.autocomplete-item:hover,
.autocomplete-active {
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
  transition: border-color 0.3s ease, transform 0.3s ease;
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
.staged-list-enter-active { transition: opacity 0.3s ease, transform 0.3s ease; }
.staged-list-leave-active { transition: opacity 0.2s ease, transform 0.2s ease; }
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
.badge-warning { background: #fef3c7; color: #92400e; }
.so-stock-warning { text-align: center; padding: 8px 0; }
.so-stock-warning-icon { font-size: 40px; color: var(--color-warning-500, #f59e0b); margin-bottom: 12px; }
.so-stock-warning-title { font-size: 15px; font-weight: 600; color: var(--color-text-primary); margin: 0 0 16px; }
.so-stock-warning-detail { display: inline-block; text-align: left; background: var(--color-bg-secondary, #f8fafc); border-radius: 10px; padding: 12px 20px; }
.so-stock-warning-row { display: flex; justify-content: space-between; gap: 24px; padding: 6px 0; font-size: 13px; }
.so-stock-warning-row + .so-stock-warning-row { border-top: 1px solid var(--color-border-light, #f1f5f9); }
.so-stock-warning-label { color: var(--color-text-secondary); }
.so-stock-warning-value { font-weight: 500; color: var(--color-text-primary); }
.so-stock-warning-num { font-variant-numeric: tabular-nums; }
.so-stock-warning-demand { color: var(--color-danger-500, #ef4444); }
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
  transition: background 0.2s ease, transform 0.2s ease;
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
  transition: border-color 0.2s ease, color 0.2s ease, transform 0.2s ease;
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

/* ===== Table ===== */
.so-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.so-table thead {
  background: var(--color-surface, #f8fafc);
  position: sticky;
  top: 0;
  z-index: 1;
}
.so-table th {
  padding: 10px 12px;
  text-align: center;
  font-weight: 600;
  color: var(--color-text-secondary);
  font-size: 12px;
  border-bottom: 2px solid var(--color-border, #cbd5e1);
  white-space: nowrap;
}
.so-table td {
  padding: 10px 12px;
  text-align: center;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
  vertical-align: middle;
}
.so-table tbody tr:hover {
  background: var(--color-primary-50);
}
.so-cell-main {
  font-weight: 500;
  color: var(--color-text);
}
.so-cell-muted {
  color: var(--color-text-muted);
  font-size: 12px;
}

/* ===== Badge Tags (records) ===== */
.so-badge-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
}
.so-badge-success {
  background: var(--color-success-100);
  color: var(--color-success-600);
}

/* ===== Action Buttons (records) ===== */
.so-action-group {
  display: flex;
  gap: 4px;
  justify-content: center;
}
.so-btn-icon {
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s ease, transform 0.2s ease;
}
.so-btn-info {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}
.so-btn-info:hover {
  background: var(--color-primary-100);
  transform: translateY(-1px);
}

/* ===== Loading & Empty States ===== */
.so-state-placeholder {
  text-align: center;
  padding: 60px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}
.so-state-empty {
  color: var(--color-text-muted);
}
.so-state-text {
  font-size: 14px;
  color: var(--color-text-secondary);
  margin: 0;
}
.so-empty-illustration {
  font-size: 36px;
  opacity: 0.4;
  color: var(--color-text-muted);
}
.so-spinner-ring {
  width: 36px;
  height: 36px;
  border: 3px solid var(--color-border-light);
  border-top-color: var(--color-danger-500);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

/* ===== Fetching Progress Bar ===== */
.so-fetching-bar {
  height: 3px;
  background: var(--color-border-light);
  overflow: hidden;
}
.so-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500);
  animation: so-progress-slide 1.2s ease-in-out infinite;
}
@keyframes so-progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}

/* ===== Detail Dialog ===== */
.so-detail-dialog {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.so-detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 12px;
  overflow: hidden;
}
.so-detail-cell {
  padding: 10px 16px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
}
.so-detail-cell:nth-child(odd) {
  border-right: 1px solid var(--color-border-light, #e2e8f0);
}
.so-detail-cell:nth-last-child(-n+2) {
  border-bottom: none;
}
.so-detail-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.so-detail-value {
  font-size: 14px;
  font-weight: 500;
  color: var(--color-text);
}
.so-detail-mono {
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  letter-spacing: 0.02em;
}
.so-detail-note {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 16px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 12px;
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
  .so-filter-row {
    flex-direction: column;
  }
  .so-filter-field {
    min-width: 100%;
  }
  .so-table {
    font-size: 12px;
  }
  .so-table th, .so-table td {
    padding: 8px 6px;
  }
  .so-detail-grid {
    grid-template-columns: 1fr;
  }
  .so-detail-cell:nth-child(odd) {
    border-right: none;
  }
}
</style>
