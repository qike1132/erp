<template>
  <div class="so-col-title">
    <span>出货信息录入</span>
    <UiBadge v-if="stagedCount" variant="cancelled">已暂存: {{ stagedCount }}</UiBadge>
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
          <UiSelect v-model="form.country" placeholder="请选择国家" :options="countryOptions" />
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
          :searchFn="searchFn"
          placeholder="输入产品名称或69码搜索"
          @select="onSelect"
          @update:modelValue="onSearchInput"
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
        @click="emit('add-staged')"
        style="margin-top: 15px"
      >
        <FontAwesomeIcon icon="plus-circle" aria-hidden="true" />新增出货
      </UiButton>
    </form>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { stockApi } from '@/api'
import type { ApiResponse, ShipmentInfo, Product } from '@/types'
import { useOcrImport } from '../composables/useOcrImport'
import { showToast } from '@/composables/useToast'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiBadge from '@/components/ui/UiBadge.vue'

interface StockOutForm {
  customer: string
  date: string
  search: string
  productId: string
  quantity: number
  note: string
  orderType: string
  country: string
}

defineProps<{
  customerOptions: { value: string; label: string }[]
  countryOptions: { value: string; label: string }[]
  orderTypeOptions: { value: string; label: string }[]
  shipmentInfo: ShipmentInfo | null
  canAdd: boolean
  stagedCount: number
  searchFn: (q: string) => Promise<Product[]>
}>()

const form = defineModel<StockOutForm>('form', { required: true })

const emit = defineEmits<{
  'add-staged': []
  'product-select': [product: Product]
  'clear-shipment': []
  imported: []
}>()

function onSelect(product: Product) {
  emit('product-select', product)
}

function onSearchInput() {
  form.value.productId = ''
  emit('clear-shipment')
}

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
    await stockApi.downloadTemplate()
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
            emit('imported')
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
  emit('imported')
})
</script>

<style scoped>
/* ===== 强制覆盖产品名称输入框灰色背景（PT HMR 不重载 main.ts 的双保险） ===== */
:deep(input.bg-slate-50) {
  background-color: #ffffff !important;
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
.so-section-body-compact {
  padding: 2px 12px 4px;
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

/* ===== Responsive ===== */
@media (max-width: 767.98px) {
  .form-grid { grid-template-columns: 1fr; }
}
</style>
