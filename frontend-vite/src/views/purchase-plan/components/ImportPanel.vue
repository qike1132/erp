<template>
  <div>
    <div
      class="csd-upload-area"
      :class="{ 'csd-upload-hover': dragOver }"
      @click="fileInp?.click()"
      @dragover.prevent="dragOver = true"
      @dragleave="dragOver = false"
      @drop.prevent="onDrop"
    >
      <div class="csd-upload-label">
        <FontAwesomeIcon icon="file-excel" aria-hidden="true" />
        <span v-if="file" class="csd-file-selected"><FontAwesomeIcon icon="check-circle" aria-hidden="true" />{{ file.name }}</span>
        <span v-else>拖拽文件到此处或点击选择 · 支持 .xlsx .xls .csv</span>
      </div>
      <div class="csd-upload-buttons">
        <button class="csd-inline-btn" @click.stop="dlTpl">模板</button>
        <button class="csd-inline-btn csd-inline-btn-primary" :disabled="!file || uploading" @click.stop="doUpload">
          <FontAwesomeIcon v-if="!uploading" icon="upload" aria-hidden="true" />
          <FontAwesomeIcon v-else icon="spinner" spin /> 导入
        </button>
        <button v-if="file" class="csd-inline-btn csd-inline-btn-danger" @click.stop="clearFile" aria-label="删除">
          <FontAwesomeIcon icon="trash" aria-hidden="true" />
        </button>
      </div>
      <input ref="fileInp" type="file" accept=".xlsx,.xls,.csv" hidden @change="onFile" />
    </div>
    <div v-if="upMsg" class="csd-upload-message" :class="{ 'csd-upload-success': upOk, 'csd-upload-error': !upOk }">
      <FontAwesomeIcon :icon="upOk ? 'check-circle' : 'exclamation-circle'" aria-hidden="true" />
      {{ upMsg }}
    </div>
  </div>
</template>

<script setup lang="ts">
// 出货计划「批量导入」面板（从 CreateShipmentPlanDialog.vue 抽出，模板与上传逻辑原样搬移）
import { ref, watch } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { planApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'

const props = defineProps<{ open: boolean }>()

const emit = defineEmits<{
  created: []
}>()

const qc = useQueryClient()

// 批量导入相关
const file = ref<File | null>(null)
const fileInp = ref<HTMLInputElement | null>(null)
const dragOver = ref(false)
const uploading = ref(false)
const upMsg = ref('')
const upOk = ref(true)
let _ut: ReturnType<typeof setTimeout> | null = null

// 批量导入功能
function onDrop(ev: DragEvent) { dragOver.value = false; const fs = ev.dataTransfer?.files; if (fs?.length && fs[0]) vfile(fs[0]) }
function onFile(ev: Event) { const t2 = ev.target as HTMLInputElement; if (t2.files?.length && t2.files[0]) vfile(t2.files[0]); t2.value = '' }
function vfile(f: File) { clearUpMsg(); const ext = '.' + (f.name.split('.').pop()?.toLowerCase() ?? ''); if (!['.xlsx', '.xls', '.csv'].includes(ext)) { showUpMsg('仅支持 .xlsx .xls .csv', false); return; } if (f.size > 10 * 1024 * 1024) { showUpMsg('文件超过 10MB', false); return; } if (f.size === 0) { showUpMsg('文件为空', false); return; } file.value = f }
function clearFile() { file.value = null; clearUpMsg() }
async function doUpload() { if (!file.value) return; uploading.value = true; clearUpMsg(); try { const fd = new FormData(); fd.append('file', file.value); const r = await planApi.upload(fd) as { total?: number }; showUpMsg(`导入成功，共 ${r.total || 0} 条`, true); clearFile(); qc.invalidateQueries({ queryKey: ['pp-monthly'] }); qc.invalidateQueries({ queryKey: ['pp-summary'] }); emit('created') } catch (e: unknown) { showUpMsg(getErrorMessage(e, '导入失败'), false) } finally { uploading.value = false } }
function showUpMsg(msg: string, ok: boolean) { upMsg.value = msg; upOk.value = ok; if (_ut) clearTimeout(_ut); _ut = setTimeout(() => upMsg.value = '', 5000) }
function clearUpMsg() { upMsg.value = ''; if (_ut) clearTimeout(_ut) }
async function dlTpl() { try { await planApi.downloadTemplate() } catch { showToast('下载失败', 'error') } }

// 对话框打开时清空已选文件（与原 watch(open) 中 clearFile 行为一致）
watch(() => props.open, (val) => { if (val) clearFile() })
</script>

<style scoped>
.csd-upload-area {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  background: white;
  border: 2px dashed var(--color-border-light, #e2e8f0);
  border-radius: 11px;
  cursor: pointer;
  transition: border-color 0.3s ease, background 0.3s ease;
  flex-wrap: wrap;
}
.csd-upload-hover {
  border-color: var(--color-success-400);
  background: var(--color-success-50);
}
.csd-upload-area:hover {
  border-color: var(--color-primary-300);
}
.csd-upload-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 400;
  color: var(--color-text-muted);
  font-family: inherit;
}
.csd-upload-label i {
  color: var(--color-text-muted);
  font-size: 16px;
}
.csd-file-selected {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-success-600);
}
.csd-upload-buttons {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}
.csd-inline-btn {
  padding: 4px 10px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 7px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: border-color 0.2s ease, color 0.2s ease, background 0.2s ease;
  background: var(--color-surface);
  color: var(--color-text-secondary);
  font-family: inherit;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.csd-inline-btn:hover:not(:disabled) {
  border-color: var(--color-primary-300);
  color: var(--color-primary-500);
  background: var(--color-primary-50);
}
.csd-inline-btn-primary {
  background: var(--color-primary-500);
  border-color: var(--color-primary-500);
  color: white;
}
.csd-inline-btn-primary:hover:not(:disabled) {
  background: var(--color-primary-600);
  border-color: var(--color-primary-600);
  color: white;
}
.csd-inline-btn-danger {
  background: var(--color-danger-50);
  border-color: var(--color-danger-200);
  color: var(--color-danger-500);
}
.csd-inline-btn-danger:hover:not(:disabled) {
  background: var(--color-danger-100);
  border-color: var(--color-danger-300);
  color: var(--color-danger-600);
}
.csd-inline-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.csd-upload-message {
  margin-top: 8px;
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 6px;
}
.csd-upload-success {
  background: var(--color-success-50);
  color: var(--color-success-600);
  border: 1px solid var(--color-success-200);
}
.csd-upload-error {
  background: var(--color-danger-50);
  color: var(--color-danger-600);
  border: 1px solid var(--color-danger-200);
}
</style>
