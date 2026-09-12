<template>
  <div class="bi-card">
    <div class="bi-header" role="button" tabindex="0" :aria-expanded="open" aria-label="批量导入" @click="open = !open" @keydown.enter.prevent="open = !open">
      <div class="bi-title">
        <FontAwesomeIcon :icon="mode === 'stockin' ? 'file-import' : 'file-export'" :style="{ color: accent }" aria-hidden="true" />
        Excel 批量导入
      </div>
      <FontAwesomeIcon icon="chevron-down" :class="['bi-arrow', { expanded: open }]" aria-hidden="true" />
    </div>
    <div v-if="open" class="bi-content">
      <UiUpload accept=".xlsx,.xls" placeholder="拖拽 Excel 文件到这里，或点击选择文件（支持 .xlsx / .xls）" @change="emit('excel-change', $event)" />
      <div v-if="excelFile" class="bi-file-selected">
        <FontAwesomeIcon icon="file-excel" style="color: var(--color-success-500); margin-right: 6px" aria-hidden="true" />{{ excelFile.name }}
      </div>
      <div class="bi-actions">
        <button class="bi-btn bi-btn-outline" :disabled="templateDownloading" aria-label="下载模板" @click="emit('download-template')">
          <UiLoadingIcon :loading="templateDownloading" icon="file-excel" style="margin-right: 4px" />下载模板
        </button>
        <button class="bi-btn bi-btn-primary" :disabled="!excelFile || importing" :aria-label="importing ? '导入中' : '开始导入'" @click="emit('import')">
          <UiLoadingIcon :loading="importing" icon="upload" style="margin-right: 4px" />{{ importing ? '导入中…' : '开始导入' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * BatchImportCard — Excel 模板下载 + 批量导入（batch 域接口）。
 */
import { computed } from 'vue'
import UiUpload from '@/components/ui/UiUpload.vue'
import UiLoadingIcon from '@/components/ui/UiLoadingIcon.vue'
import type { StockMode } from '../composables/useCaseStockWorkbench'

const props = defineProps<{
  mode: StockMode
  excelFile: File | null
  importing: boolean
  templateDownloading: boolean
}>()

const open = defineModel<boolean>('open', { default: false })

const emit = defineEmits<{
  'excel-change': [files: FileList]
  'download-template': []
  import: []
}>()

const accent = computed(() => (props.mode === 'stockin' ? 'var(--color-primary-500)' : 'var(--color-danger-500)'))
</script>

<style scoped>
.bi-card {
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 13px;
  overflow: hidden;
  background: var(--color-surface-card, white);
}
.bi-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  cursor: pointer;
  user-select: none;
}
.bi-header:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: -2px; }
.bi-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
}
.bi-arrow { color: var(--color-text-muted); transition: transform 0.25s ease; }
.bi-arrow.expanded { transform: rotate(180deg); }
.bi-content { padding: 0 16px 14px; border-top: 1px solid var(--color-border-light, #f1f5f9); padding-top: 12px; }
.bi-file-selected { margin-top: 8px; font-size: 13px; color: var(--color-text-secondary); }
.bi-actions { display: flex; justify-content: space-between; align-items: center; margin-top: 12px; }
.bi-btn {
  padding: 6px 12px;
  border-radius: 9px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  transition: background 0.2s ease, transform 0.2s ease;
}
.bi-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.bi-btn-outline {
  border: 2px solid var(--color-border-light, #e2e8f0);
  background: white;
  color: var(--color-text-secondary);
}
.bi-btn-outline:hover:not(:disabled) { background: var(--color-surface, #f8fafc); }
.bi-btn-primary {
  border: none;
  color: white;
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700));
}
.bi-btn-primary:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(91, 141, 239, 0.3); }
</style>
