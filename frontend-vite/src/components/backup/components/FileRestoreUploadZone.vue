<template>
  <div class="bk-section">
    <div class="bk-section-label">选择备份文件</div>
    <div
      class="bk-drop-zone"
      :class="{ 'bk-drop-active': dragOver }"
      tabindex="0"
      role="button"
      aria-label="选择备份文件"
      @click="fileInputRef?.click()"
      @keydown.enter="fileInputRef?.click()"
      @keydown.space.prevent="fileInputRef?.click()"
      @dragover.prevent="dragOver = true"
      @dragleave="dragOver = false"
      @drop.prevent="handleDrop"
    >
      <div v-if="selectedFile" class="bk-file-info">
        <FontAwesomeIcon icon="file-alt" />
        <span class="bk-file-name">{{ selectedFile.name }}</span>
        <span class="bk-file-size">({{ formatSize(selectedFile.size) }})</span>
        <button class="bk-file-clear" aria-label="关闭" @click.stop="handleClear"><FontAwesomeIcon icon="times" /></button>
      </div>
      <div v-else class="bk-drop-hint">
        <FontAwesomeIcon icon="cloud-upload-alt" />
        <span>拖拽 .zip / .json / .gz 备份文件到此处，或点击选择</span>
      </div>
    </div>
    <input ref="fileInputRef" type="file" accept=".zip,.json,.gz" style="display: none" aria-label="上传文件" @change="onFileSelect" />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

defineProps<{
  selectedFile: File | null
}>()

const emit = defineEmits<{
  (e: 'file-select', file: File): void
  (e: 'file-clear'): void
}>()

const fileInputRef = ref<HTMLInputElement | null>(null)
const dragOver = ref(false)

function onFileSelect(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) emit('file-select', file)
}

function handleDrop(e: DragEvent) {
  dragOver.value = false
  const file = e.dataTransfer?.files?.[0]
  if (file) emit('file-select', file)
}

function handleClear() {
  if (fileInputRef.value) fileInputRef.value.value = ''
  emit('file-clear')
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}
</script>

<style scoped>
.bk-section { margin-bottom: 20px; }

.bk-section-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  margin-bottom: 8px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.bk-drop-zone {
  border: 2px dashed var(--color-ocean-light);
  border-radius: var(--radius-input);
  padding: 28px 20px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.3s ease, background 0.3s ease;
  background: white;
}

.bk-drop-zone:hover,
.bk-drop-active {
  border-color: var(--color-ocean-deep);
  background: var(--color-ocean-light);
}

.bk-drop-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  color: var(--color-text-muted);
  font-size: 14px;
  font-weight: 400;
}

.bk-drop-hint i {
  font-size: 28px;
  color: var(--color-primary-300);
}

.bk-file-info {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--color-text);
  font-size: 14px;
}

.bk-file-info > i {
  color: var(--color-success-500);
}

.bk-file-name { font-weight: 600; }

.bk-file-size {
  color: var(--color-text-secondary);
  font-size: 12px;
}

.bk-file-clear {
  background: none;
  border: none;
  color: var(--color-text-muted);
  cursor: pointer;
  padding: 4px;
  border-radius: 50%;
  transition: background 0.2s ease, color 0.2s ease;
}

.bk-file-clear:hover {
  background: var(--color-danger-50);
  color: var(--color-danger-500);
}
</style>