<template>
  <div :class="['relative', containerClass]">
    <input
      ref="fileInput"
      type="file"
      :accept="accept"
      :multiple="multiple"
      :disabled="disabled"
      class="hidden"
      @change="handleFileChange"
    />
    <div @click="triggerUpload">
      <slot>
        <div
          :class="[
            'flex flex-col items-center justify-center border-2 border-dashed border-border rounded-xl py-8 px-4 cursor-pointer transition-all',
            disabled ? 'opacity-50 cursor-not-allowed' : 'hover:border-primary-500 hover:bg-primary-50/50',
            dragOver ? 'border-primary-500 bg-primary-50/50' : '',
          ]"
          @dragover.prevent="dragOver = true"
          @dragleave="dragOver = false"
          @drop.prevent="handleDrop"
        >
          <i class="fas fa-cloud-upload-alt text-3xl text-text-muted mb-2" />
          <p class="text-sm text-text-secondary">
            {{ placeholder }}
          </p>
        </div>
      </slot>
    </div>
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
  const files = (event.target as HTMLInputElement).files
  if (files) emit('change', files)
}

function handleDrop(event: DragEvent) {
  dragOver.value = false
  const files = event.dataTransfer?.files
  if (files) emit('change', files)
}
</script>
