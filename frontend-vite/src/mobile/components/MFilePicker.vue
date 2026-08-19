<template>
  <div class="m-file-picker">
    <button class="m-file-trigger" @click="triggerInput" :aria-label="label">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="24" height="24">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
        <polyline points="17 8 12 3 7 8" />
        <line x1="12" y1="3" x2="12" y2="15" />
      </svg>
      <span class="m-file-text">{{ label }}</span>
    </button>
    <input
      ref="inputRef"
      type="file"
      :accept="accept"
      :multiple="multiple"
      class="m-file-input"
      @change="handleChange"
    />
    <div v-if="files.length" class="m-file-list">
      <div v-for="(file, i) in files" :key="i" class="m-file-item">
        <span class="m-file-name">{{ file.name }}</span>
        <button class="m-file-remove" @click="removeFile(i)" aria-label="关闭">&times;</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  label?: string
  accept?: string
  multiple?: boolean
}>()
const emit = defineEmits<{ (e: 'select', files: File[]): void }>()

const inputRef = ref<HTMLInputElement>()
const files = ref<File[]>([])

function triggerInput() {
  inputRef.value?.click()
}

function handleChange(e: Event) {
  const target = e.target as HTMLInputElement
  const newFiles = Array.from(target.files ?? [])
  files.value = props.multiple ? [...files.value, ...newFiles] : newFiles
  emit('select', files.value)
  target.value = ''
}

function removeFile(index: number) {
  files.value.splice(index, 1)
  emit('select', files.value)
}
</script>

<style scoped>
.m-file-input {
  display: none;
}

.m-file-trigger {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  padding: 24px;
  border: 2px dashed rgba(0, 0, 0, 0.1);
  border-radius: var(--m-radius-md);
  background: var(--m-bg-grouped);
  color: var(--m-text-secondary);
  cursor: pointer;
  font-family: inherit;
  -webkit-tap-highlight-color: transparent;
}

.m-file-trigger:active {
  border-color: var(--m-accent);
  color: var(--m-accent);
}

.m-file-text {
  font-size: 14px;
  font-weight: 500;
}

.m-file-list {
  margin-top: 8px;
}

.m-file-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: var(--m-bg-surface);
  border-radius: 8px;
  margin-bottom: 4px;
  font-size: 13px;
}

.m-file-name {
  color: var(--m-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.m-file-remove {
  border: none;
  background: none;
  color: var(--m-accent-rose);
  font-size: 18px;
  cursor: pointer;
  padding: 0 4px;
}
</style>
