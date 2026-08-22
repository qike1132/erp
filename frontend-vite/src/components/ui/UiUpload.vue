<template>
  <div :class="['relative', containerClass]">
    <input
      ref="fileInput"
      type="file"
      :accept="accept"
      :multiple="multiple"
      :disabled="disabled"
      :name="name"
      class="hidden"
      aria-label="文件上传"
      @change="handleFileChange"
    />
    <button type="button" class="w-full text-left" :disabled="disabled" :aria-label="placeholder" @click="triggerUpload">
      <slot>
        <div
          :class="[
            'flex flex-col items-center justify-center border-2 border-dashed border-border rounded-xl py-8 px-4 cursor-pointer transition-colors',
            disabled ? 'opacity-50 cursor-not-allowed' : 'hover:border-primary-500 hover:bg-primary-50/50',
            dragOver ? 'border-primary-500 bg-primary-50/50' : '',
          ]"
          @dragover.prevent="dragOver = true"
          @dragleave="dragOver = false"
          @drop.prevent="handleDrop"
        >
          <FontAwesomeIcon icon="cloud-upload-alt" class="text-3xl text-text-muted mb-2" aria-hidden="true" />
          <p class="text-sm text-text-secondary">
            {{ placeholder }}
          </p>
        </div>
      </slot>
    </button>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

defineProps<{
  accept?: string
  multiple?: boolean
  disabled?: boolean
  placeholder?: string
  containerClass?: string
  name?: string
}>()

const emit = defineEmits<{
  change: [files: FileList]
}>()

const fileInput = ref<HTMLInputElement | null>(null)
const dragOver = ref(false)

function triggerUpload() {
  fileInput.value?.click()
}

function handleFileChange(event: Event) {
  const target = event.target as HTMLInputElement
  const files = target.files
  if (files) emit('change', files)
  target.value = ''
}

function handleDrop(event: DragEvent) {
  dragOver.value = false
  const files = event.dataTransfer?.files
  if (files) emit('change', files)
}
</script>
