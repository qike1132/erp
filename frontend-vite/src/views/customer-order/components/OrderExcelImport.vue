<template>
  <div class="co-section-label"><FontAwesomeIcon icon="file-import" aria-hidden="true" /> 批量导入</div>
  <div
    class="co-section-header co-droppable"
    :class="{ 'co-drag-over': isDragOver }"
    @click="excelInputRef?.click()"
    @dragover.prevent="$emit('update:isDragOver', true)"
    @dragleave="$emit('update:isDragOver', false)"
    @drop.prevent="onDrop"
  >
    <label class="form-label co-droppable-label">
      <FontAwesomeIcon icon="file-excel" class="label-icon" aria-hidden="true" />
      <span v-if="excelFile" class="co-file-inline co-file-inline-success"><FontAwesomeIcon icon="file-excel" aria-hidden="true" />{{ excelFile.name }}</span>
      <span v-else>拖拽文件到标题栏 · 支持 .xlsx / .xls</span>
    </label>
    <div class="co-inline-actions">
      <button class="co-inline-btn" @click.stop="downloadTemplate" aria-label="模板 {{ importing ? '导入中…' : '导入' }}">模板</button>
      <button class="co-inline-btn co-inline-btn-success" :disabled="!excelFile" @click.stop="handleImport" :aria-label="importing ? '导入中…' : '导入'">
        {{ importing ? '导入中…' : '导入' }}
      </button>
    </div>
    <input
      ref="excelInputRef"
      type="file"
      accept=".xlsx,.xls"
      style="display: none"
      @change="handleExcelSelect"
    />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

defineProps<{
  excelFile: File | null
  importing: boolean
  isDragOver: boolean
  handleExcelSelect: (e: Event) => void
  onDrop: (e: DragEvent) => void
  downloadTemplate: () => void
  handleImport: () => void
}>()

defineEmits<{
  'update:isDragOver': [value: boolean]
}>()

const excelInputRef = ref<HTMLInputElement | null>(null)
</script>

<style scoped>
.co-section-header {
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
.co-section-header:hover {
  border-color: var(--color-ocean-deep);
  background: var(--color-slate-50);
}
.co-section-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  padding: 8px 0 4px;
}
.co-droppable { cursor: pointer; }
.co-droppable.co-drag-over {
  border-color: var(--color-success-400);
  background: var(--color-success-50);
}
.co-droppable-label {
  display: flex !important;
  margin-bottom: 0;
  cursor: pointer;
  font-size: 14px !important;
  font-weight: 400 !important;
  color: var(--color-text-muted) !important;
}
.co-droppable-label .label-icon {
  color: var(--color-text-muted) !important;
}
.co-inline-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}
.co-inline-btn {
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
.co-inline-btn:hover {
  border-color: var(--color-ocean-deep);
  color: var(--color-primary-600);
}
.co-inline-btn-success {
  border-color: var(--color-success-400);
  color: var(--color-success-600);
}
.co-inline-btn-success:hover {
  background: var(--color-success-50);
}
.co-inline-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.co-file-inline {
  font-size: 13px;
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.co-file-inline-success {
  color: var(--color-success-600);
}
</style>