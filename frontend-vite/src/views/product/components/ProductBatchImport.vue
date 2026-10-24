<template>
  <div class="pd-section-label"><FontAwesomeIcon icon="file-import" aria-hidden="true" /> 批量导入</div>
  <div
    class="pd-section-header pd-droppable"
    :class="{ 'pd-drag-over': excelDragOver }"
    @click="excelInputRef?.click()"
    @dragover.prevent="excelDragOver = true"
    @dragleave="excelDragOver = false"
    @drop.prevent="onExcelDrop"
  >
    <label class="form-label pd-droppable-label">
      <FontAwesomeIcon icon="file-excel" class="label-icon" aria-hidden="true" />
      <span v-if="excelFile" class="pd-file-inline pd-file-inline-success"><FontAwesomeIcon icon="file-excel" />{{ excelFile.name }}</span>
      <span v-else>拖拽文件到标题栏 · 支持 .xlsx / .xls</span>
    </label>
    <div class="pd-inline-actions">
      <button class="pd-inline-btn" aria-label="模板 下载" @click.stop="downloadTemplate">模板</button>
      <button
        class="pd-inline-btn pd-inline-btn-preview"
        :disabled="!excelFile || previewing"
        :aria-label="previewing ? '预览中…' : '预览'"
        @click.stop="handlePreview"
      >
        {{ previewing ? '预览中…' : '预览' }}
      </button>
    </div>
    <input ref="excelInputRef" type="file" style="display: none" accept=".xlsx,.xls" name="file" aria-label="file" @change="onExcelSelect" />
  </div>

  <ProductImportPreviewModal
    v-model:open="showPreview"
    :result="previewResult"
    :importing="importing"
    @confirm="handleConfirmImport"
  />
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { batchApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'
import ProductImportPreviewModal from './ProductImportPreviewModal.vue'
import type { ProductImportPreviewResult } from '@/types/api'

const queryClient = useQueryClient()

const excelFile = ref<File | null>(null)
const excelInputRef = ref<HTMLInputElement | null>(null)
const excelDragOver = ref(false)
const previewing = ref(false)
const importing = ref(false)
const showPreview = ref(false)
const previewResult = ref<ProductImportPreviewResult | null>(null)

function onExcelSelect(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  // F1b-04（2026-10-24 审计）：清值，同 BackupView 修法——否则导入后重传
  // 同一文件第二次点击无反应。
  input.value = ''
  if (file) handleExcelFile(file)
}
function onExcelDrop(e: DragEvent) {
  excelDragOver.value = false
  const file = e.dataTransfer?.files[0]
  if (file) handleExcelFile(file)
}

function handleExcelFile(file: File) {
  const name = file.name.toLowerCase()
  if (!name.endsWith('.xlsx') && !name.endsWith('.xls')) { showToast('请上传 Excel 文件（.xlsx 或 .xls）', 'error'); return }
  excelFile.value = file
}

function buildFormData(): FormData {
  const formData = new FormData()
  formData.append('file', excelFile.value as File)
  return formData
}

/**
 * 预览：先看清「将新增/补全/跳过什么、客户与价格识别成什么」，再决定要不要入库。
 *
 * 文件级错误（格式不对、解析失败）没有可核对的行 → 直接提示，不弹窗；
 * 只要解析出了行就打开弹窗（哪怕全部不可导入，也让用户看到原因）。
 */
async function handlePreview() {
  if (!excelFile.value) return
  previewing.value = true
  try {
    const result = await batchApi.previewProducts(buildFormData())
    if (!result.rows?.length) {
      showToast(result.message || '预览失败', 'error')
      return
    }
    previewResult.value = result
    showPreview.value = true
  } catch (err: unknown) {
    showToast(getErrorMessage(err, '预览失败'), 'error')
  } finally {
    previewing.value = false
  }
}

/** 确认导入：把浏览器里留着的同一份文件重发给导入端点（写入在这里才发生）。 */
async function handleConfirmImport() {
  if (!excelFile.value) return
  importing.value = true
  try {
    const result = await batchApi.importProducts(buildFormData())
    // 按后端结果如实提示：`success=false`（例如「产品都已存在，未改动」）与行级问题
    // 都写在 message 里。以前无视结果一律弹「导入成功」，把「其实一条都没更新」
    // 显示成成功，用户据此以为「客户和价格识别不了」。
    showToast(result.message || (result.success ? '导入成功' : '导入失败'), result.success ? 'success' : 'error')
    if (result.success) {
      excelFile.value = null
      showPreview.value = false
      previewResult.value = null
    }
    queryClient.invalidateQueries({ queryKey: ['products-list'] })
  } catch (err: unknown) {
    showToast(getErrorMessage(err, '导入失败'), 'error')
  } finally {
    importing.value = false
  }
}

function downloadTemplate() {
  // F1b-05（2026-10-24 审计）：补 catch——失败此前静默 + unhandled rejection
  // （对照 useCaseStockWorkbench.ts:249 的同款处理）。
  batchApi.downloadTemplate('产品导入模板.xlsx').catch(() => {
    showToast('模板下载失败，请稍后重试', 'error')
  })
}
</script>

<style scoped>
.pd-section-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  padding: 8px 0 4px;
}

.pd-section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: white;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: var(--radius-input, 12px);
  min-height: 40px;
  box-sizing: border-box;
  cursor: default;
  transition: border-color 0.3s ease, background 0.3s ease;
}
.pd-section-header:hover {
  border-color: var(--color-ocean-deep);
  background: var(--color-slate-50);
}
.pd-droppable { cursor: pointer; }
.pd-droppable.pd-drag-over {
  border-color: var(--color-success-400);
  background: var(--color-success-50);
}
.pd-droppable-label {
  display: flex !important;
  margin-bottom: 0;
  cursor: pointer;
  font-size: 14px !important;
  font-weight: 400 !important;
  color: var(--color-text-muted) !important;
  align-items: center;
}
.pd-droppable-label .label-icon {
  color: var(--color-text-muted) !important;
}
.pd-inline-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}
.pd-inline-btn {
  padding: 3px 8px;
  border: 1px solid var(--color-border-light);
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  background: white;
  color: var(--color-text-secondary);
  transition: border-color 0.2s ease, color 0.2s ease;
}
.pd-inline-btn:hover {
  border-color: var(--color-ocean-deep);
  color: var(--color-primary-600);
}
.pd-inline-btn-preview {
  border-color: var(--color-primary-500);
  color: var(--color-primary-600);
  background: var(--color-primary-50);
}
.pd-inline-btn-preview:hover {
  background: var(--color-primary-100);
}
.pd-inline-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.pd-file-inline {
  font-size: 13px;
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.pd-file-inline-success {
  color: var(--color-success-600);
}
</style>
