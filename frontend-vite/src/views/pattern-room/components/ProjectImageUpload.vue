<template>
  <div class="pjf-image-section">
    <div v-if="previewUrl" class="pjf-image-preview">
      <img loading="lazy" :src="previewUrl" alt="预览" class="pjf-img" />
      <button class="pjf-img-remove" aria-label="移除图片" @click="emit('remove')">&times;</button>
    </div>
    <label
      v-else
      :class="['pjf-upload-area', { 'pjf-upload-area--dragover': isDragOver }]"
      @dragover.prevent="onDragOver"
      @dragleave.prevent="onDragLeave"
      @drop.prevent="onDrop"
    >
      <input type="file" accept="image/jpeg,image/png,image/webp" class="pjf-file-input" aria-label="上传文件" @change="onFileChange" />
      <FontAwesomeIcon icon="cloud-upload-alt" aria-hidden="true" />
      <span>点击或拖拽图片到此处上传</span>
      <span class="pjf-upload-hint">支持 JPEG/PNG/WebP，上传前自动压缩（≤1600px）</span>
    </label>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  previewUrl: string | null
  isDragOver: boolean
  onFileChange: (e: Event) => void
  onDragOver: (e: DragEvent) => void
  onDragLeave: () => void
  onDrop: (e: DragEvent) => void
}>()

const emit = defineEmits<{
  remove: []
}>()
</script>

<style scoped>
.pjf-image-section {
  margin-top: 4px;
}
.pjf-image-preview {
  position: relative;
  display: inline-block;
}
.pjf-img {
  max-width: 200px;
  max-height: 200px;
  border-radius: 8px;
  border: 1px solid var(--color-border-light);
  object-fit: cover;
}
.pjf-img-remove {
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
.pjf-upload-area {
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
.pjf-upload-area:hover {
  border-color: var(--color-primary-400);
}
.pjf-upload-area--dragover {
  border-color: var(--color-primary-500);
  background: color-mix(in srgb, var(--color-primary-500) 8%, transparent);
}
.pjf-upload-area i {
  font-size: 24px;
  opacity: 0.6;
}
.pjf-file-input {
  display: none;
}
.pjf-upload-hint {
  font-size: 11px;
  opacity: 0.6;
}
</style>