<template>
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
      <button class="so-inline-btn" :disabled="templateDownloading" aria-label="模板" @click.stop="handleDownloadTemplate">
        <UiLoadingIcon :loading="templateDownloading" icon="download" />模板
      </button>
      <button class="so-inline-btn so-inline-btn-success" :disabled="!excelFile || importing" :aria-label="importing ? '导入中' : '导入'" @click.stop="handleImportExcel">
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

  <!-- 粘贴识别：与客户订单页共用 components/ocr，确认后映射成暂存出货条目 -->
  <div class="so-section-label"><FontAwesomeIcon icon="paste" aria-hidden="true" /> 粘贴识别</div>
  <OcrPasteImport
    :build-staged="buildStaged"
    :default-customer="customer"
    :default-date="date"
    :search-products="searchProducts"
    :download-template="handleDownloadTemplate"
    @go-manual="emit('go-manual')"
  />
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { stockApi } from '@/api'
import type { Product, StagedStockout } from '@/types'
import OcrPasteImport from '@/components/ocr/OcrPasteImport.vue'
import { buildStockoutStagedItems } from '../composables/useStockoutOcrStaging'
import type { OcrDraftItem, OcrStagingContext } from '@/components/ocr/types'
import { showToast } from '@/composables/useToast'

/** 暂存出货确认响应（后端 StagingStockOutConfirmResult） */
interface StagingConfirmResult {
  success?: boolean
  message?: string
  confirmed?: number
  errors?: string[]
}

const props = defineProps<{
  /** 表单当前选中的客户：识别结果缺客户时的兜底 */
  customer: string
  /** 表单当前选中的出货时间 */
  date: string
  searchProducts: (q: string) => Promise<Product[]>
  /**
   * 父级冻结（表单正在提交等）：此时不接受换选文件。
   * 与组件自身的 importing 共同构成文件入口冻结谓词，见 rejectIfFrozen。
   */
  disabled?: boolean
}>()

const emit = defineEmits<{
  imported: []
  /** OCR 确认后的暂存出货条目，由上层并入暂存列表 */
  'ocr-staged': [items: StagedStockout[]]
  /** 指引态「去录入」：由录入表单把焦点交给产品输入框 */
  'go-manual': []
}>()

// === 批量导入 ===
const excelFile = ref<File | null>(null)
const importing = ref(false)
const templateDownloading = ref(false)
const excelInputRef = ref<HTMLInputElement | null>(null)
const excelDragOver = ref(false)

function onExcelFileSelect(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  // 先清后读：浏览器对同一路径重选不触发 change，读完不重置会让「导入失败修正表格后
  // 重选同一文件」彻底无反馈（无文件名、无 toast、按钮保持禁用）。必须在守卫**之前**
  // 无条件清，否则冻结拒绝/格式不符的早退路径会把 value 留着（R30-L10）。
  input.value = ''
  if (!file) return
  if (rejectIfFrozen()) return
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
  if (rejectIfFrozen()) return
  if (!(file.name.endsWith('.xlsx') || file.name.endsWith('.xls'))) {
    showToast('请上传 Excel 文件（.xlsx 或 .xls）', 'error')
    return
  }
  excelFile.value = file
}

/**
 * 文件入口冻结谓词（R36 L-j）：父级冻结（props.disabled）与自身导入在途
 * （importing）都必须拒绝换选。只看 props.disabled 时，导入窗口内换选的文件会被
 * 接受，待导入成功后 handleImportExcel 把 excelFile 置 null 又把它静默丢弃——
 * 用户看到文件名直接消失、没有任何提示。两个入口（input / drop）同口径。
 */
function rejectIfFrozen(): boolean {
  if (!props.disabled && !importing.value) return false
  showToast('正在处理，请稍后再导入', 'warning')
  return true
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
    if (!res.success) {
      showToast(res.message || '导入失败', 'error')
      return
    }
    showToast(`成功导入 ${res.imported ?? 0} 条记录到暂存区`, 'success')
    excelFile.value = null
    if (!res.imported) return
    // 导入成功 ≠ 出货成功：确认失败时后端会删掉失败行并返回 success:false，
    // 旧实现把这一路完全吞掉，用户以为已出货、库存实际未减（2026-10-30 审计 A-H3）。
    try {
      const confirmRes = await stockApi.stagingStockouts.confirm(sessionId) as StagingConfirmResult
      if (confirmRes.success) {
        const n = confirmRes.confirmed
        showToast(`暂存出货已确认提交${n ? `（${n} 条）` : ''}`, 'success')
      } else {
        const detail = confirmRes.errors?.length
          ? `；失败 ${confirmRes.errors.length} 条：${confirmRes.errors.slice(0, 3).join('；')}`
          : ''
        showToast((confirmRes.message || '暂存出货确认失败，记录仍在暂存区') + detail, 'error')
      }
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } } }
      showToast(error.response?.data?.detail || '暂存出货确认失败，请到暂存区检查后重试', 'error')
    } finally {
      // 无论确认成败都要刷新：成功要显示新出货，失败要让暂存行可见
      emit('imported')
    }
  } catch (err: unknown) {
    const error = err as { response?: { data?: { detail?: string } } }
    showToast(error.response?.data?.detail || '导入失败', 'error')
  } finally {
    importing.value = false
  }
}

// === 粘贴识别（识别与闸门在共享 OcrPasteImport，这里只决定落点） ===
function buildStaged(drafts: OcrDraftItem[], ctx: OcrStagingContext): boolean {
  emit('ocr-staged', buildStockoutStagedItems(drafts, ctx))
  return true
}
</script>

<style scoped>
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
.so-droppable { cursor: pointer; }
.so-droppable.so-drag-over {
  border-color: var(--color-success-400);
  background: var(--color-success-50);
}
.so-file-inline {
  font-size: 12px;
  font-weight: 400;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.so-file-inline-success { color: var(--color-success-700); }
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
.so-inline-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>
