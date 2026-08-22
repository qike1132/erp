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
      <button class="pd-inline-btn" aria-label="模板 {{ importing ? '导入中…' : '导入' }}" @click.stop="downloadTemplate">模板</button>
      <button class="pd-inline-btn pd-inline-btn-success" :disabled="!excelFile" :aria-label="importing ? '导入中…' : '导入'" @click.stop="handleBatchImport">
        {{ importing ? '导入中…' : '导入' }}
      </button>
    </div>
    <input ref="excelInputRef" type="file" style="display: none" accept=".xlsx,.xls" name="file" aria-label="file" @change="onExcelSelect" />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { upload, download } from '@/api/request'
import { showToast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'

const queryClient = useQueryClient()

const excelFile = ref<File | null>(null)
const excelInputRef = ref<HTMLInputElement | null>(null)
const excelDragOver = ref(false)
const importing = ref(false)

function onExcelSelect(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
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

async function handleBatchImport() {
  if (!excelFile.value) return
  importing.value = true
  const formData = new FormData()
  formData.append('file', excelFile.value)
  try {
    await upload('/batch/import-products', formData)
    showToast('导入成功', 'success')
    excelFile.value = null
    queryClient.invalidateQueries({ queryKey: ['products-list'] })
  } catch (err: unknown) {
    showToast(getErrorMessage(err, '导入失败'), 'error')
  } finally {
    importing.value = false
  }
}

function downloadTemplate() {
  download('/batch/download-template', '产品导入模板.xlsx')
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
.pd-inline-btn-success {
  border-color: var(--color-success-400);
  color: var(--color-success-600);
}
.pd-inline-btn-success:hover {
  background: var(--color-success-50);
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