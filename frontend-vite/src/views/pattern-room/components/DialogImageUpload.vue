<template>
  <div class="diu-section">
    <div v-if="previewUrl" class="diu-preview">
      <img loading="lazy" :src="previewUrl" alt="预览" class="diu-img" />
      <button class="diu-img-remove" aria-label="移除图片" @click="$emit('remove')">&times;</button>
    </div>
    <label
      v-else
      :class="['diu-upload-area', { 'diu-upload-area--dragover': isDragOver }]"
      @dragover.prevent="onDragOver"
      @dragleave.prevent="onDragLeave"
      @drop.prevent="onDrop"
    >
      <input type="file" accept="image/jpeg,image/png,image/webp" class="diu-file-input" aria-label="上传文件" @change="onFileChange" />
      <FontAwesomeIcon icon="cloud-upload-alt" aria-hidden="true" />
      <span>点击或拖拽图片到此处上传</span>
      <span class="diu-upload-hint">支持 JPEG/PNG/WebP，上传前自动压缩（≤1600px）</span>
    </label>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

defineProps<{
  previewUrl: string | null
}>()

const emit = defineEmits<{
  'upload-file': [file: File]
  'remove': []
}>()

const isDragOver = ref(false)

function onFileChange(e: Event) {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  emit('upload-file', file)
  target.value = ''
}

function onDragOver(e: DragEvent) {
  if (Array.from(e.dataTransfer?.types ?? []).includes('Files')) {
    isDragOver.value = true
  }
}

function onDragLeave() {
  isDragOver.value = false
}

function onDrop(e: DragEvent) {
  isDragOver.value = false
  const file = e.dataTransfer?.files?.[0]
  if (!file) return
  emit('upload-file', file)
}
</script>

<style scoped>
.diu-section {
  margin-top: 4px;
}
.diu-preview {
  position: relative;
  display: inline-block;
}
.diu-img {
  max-width: 200px;
  max-height: 200px;
  border-radius: 8px;
  border: 1px solid var(--color-border-light);
  object-fit: cover;
}
.diu-img-remove {
  position: absolute;
  top: -8px;
  right: -8px;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  border: 1px solid var(--color-border-light);
  background: #fff;
  color: #ef4444;
  font-size: 14px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}
.diu-upload-area {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 24px;
  border: 2px dashed var(--color-border-light);
  border-radius: 10px;
  cursor: pointer;
  transition: border-color 0.2s;
  color: var(--color-text-secondary);
  font-size: 13px;
}
.diu-upload-area:hover {
  border-color: var(--color-primary-400);
}
.diu-upload-area--dragover {
  border-color: var(--color-primary-500);
  background: color-mix(in srgb, var(--color-primary-500) 8%, transparent);
}
.diu-upload-area i {
  font-size: 24px;
  opacity: 0.6;
}
.diu-file-input {
  display: none;
}
.diu-upload-hint {
  font-size: 11px;
  opacity: 0.6;
}
</style>