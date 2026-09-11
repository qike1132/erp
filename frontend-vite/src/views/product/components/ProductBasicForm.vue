<template>
  <div class="pd-section">
    <form @submit.prevent="handleAdd">
      <div class="pd-form-group">
        <label class="pd-label">产品名称</label>
        <div class="pd-input-wrap">
          <FontAwesomeIcon icon="tag" class="pd-input-icon" aria-hidden="true" />
          <input v-model="form.name" type="text" class="pd-input" required placeholder="例如：小熊毛绒玩具" name="product-name" autocomplete="off" aria-label="例如：小熊毛绒玩具" />
        </div>
      </div>
      <div class="pd-form-group">
        <label class="pd-label">69码</label>
        <div class="pd-input-wrap">
          <FontAwesomeIcon icon="barcode" class="pd-input-icon" aria-hidden="true" />
          <input v-model="form.barcode" type="text" class="pd-input" placeholder="例如：6958085574210" name="barcode" autocomplete="off" aria-label="例如：6958085574210" />
        </div>
      </div>
      <div class="pd-form-group">
        <label class="pd-label">产品价格</label>
        <div class="pd-input-wrap">
          <FontAwesomeIcon icon="yen-sign" class="pd-input-icon" aria-hidden="true" />
          <input v-model.number="form.price" type="number" class="pd-input" step="0.01" min="0" placeholder="请输入产品价格" name="price" autocomplete="off" aria-label="请输入产品价格" />
        </div>
      </div>
      <div class="pd-form-group">
        <label class="pd-label">工厂</label>
        <div class="pd-input-wrap">
          <FontAwesomeIcon icon="industry" class="pd-input-icon" aria-hidden="true" />
          <select v-model="form.factory" class="pd-input pd-select" name="factory" aria-label="工厂">
            <option value="" disabled>请选择工厂</option>
            <option v-for="f in factoryOptions" :key="f" :value="f">{{ f }}</option>
          </select>
        </div>
      </div>
      <div class="pd-form-group">
        <label class="pd-label">产品图片</label>
        <div
          ref="imageDropZoneRef"
          class="pd-section-header pd-droppable"
          :class="{ 'pd-drag-over': imageDragOver || imagePasteFlash }"
          title="点击选择、拖拽或粘贴图片"
          @click="imageInputRef?.click()"
          @dragover.prevent="onImageDragOver"
          @dragleave="imageDragOver = false"
          @drop.prevent="onImageDrop"
        >
          <label class="form-label pd-droppable-label">
            <FontAwesomeIcon icon="image" class="label-icon" aria-hidden="true" />
            <template v-if="form.image">
              <span class="pd-file-inline pd-file-inline-success">
                <img loading="lazy" :src="resolveStaticUrl(form.image)" class="pd-thumb-preview" alt="产品图片" @click.stop="emit('open-image', form.image)" />
                <button type="button" class="pd-thumb-remove" aria-label="关闭" @click.stop="form.image = ''"><FontAwesomeIcon icon="times" aria-hidden="true" /></button>
              </span>
            </template>
            <span v-else>点击选择 / 拖拽 / 粘贴图片 · 支持 {{ ALLOWED_IMAGE_HINT }}</span>
          </label>
          <input ref="imageInputRef" type="file" style="display: none" accept="image/*" name="image" @change="onImageSelect" />
        </div>
      </div>
    </form>
  </div>

  <button type="button" class="pd-btn pd-btn-primary w-full justify-center" style="margin-top: 15px" :disabled="submitting" @click="handleAdd">
    <FontAwesomeIcon icon="plus" class="me-2" aria-hidden="true" />{{ submitting ? '添加中…' : '添加产品' }}
  </button>
</template>

<script setup lang="ts">
import { ref, reactive, onBeforeUnmount } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { productApi } from '@/api'
import { resolveStaticUrl } from '@/api/request'
import { uploadImage, ALLOWED_IMAGE_HINT } from '../composables/useImageUpload'
import { useImagePaste } from '../composables/useImagePaste'
import { showToast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'

defineProps<{
  factoryOptions: readonly string[]
}>()

const emit = defineEmits<{
  'open-image': [src: string]
}>()

const queryClient = useQueryClient()

const submitting = ref(false)
const form = reactive({ name: '', barcode: '', price: 0, factory: '', image: '' })
const imageInputRef = ref<HTMLInputElement | null>(null)
const imageDropZoneRef = ref<HTMLElement | null>(null)
const imageDragOver = ref(false)
const imagePasteFlash = ref(false)

let pasteFlashTimer: ReturnType<typeof setTimeout> | undefined

/** 粘贴命中时复用拖拽高亮，给出「已接收」的即时反馈 */
function flashPasteFeedback() {
  imagePasteFlash.value = true
  clearTimeout(pasteFlashTimer)
  pasteFlashTimer = setTimeout(() => { imagePasteFlash.value = false }, 600)
}

useImagePaste({
  target: imageDropZoneRef,
  onFile: (file) => {
    flashPasteFeedback()
    uploadImageFile(file)
  },
  enabled: () => !submitting.value,
})

onBeforeUnmount(() => clearTimeout(pasteFlashTimer))

function onImageSelect(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = '' // 清空以便同一文件可重复选择
  if (file) uploadImageFile(file)
}

/** 仅在拖入真实文件时高亮，与粘贴反馈语义保持一致 */
function onImageDragOver(e: DragEvent) {
  if (e.dataTransfer?.types.includes('Files')) imageDragOver.value = true
}

function onImageDrop(e: DragEvent) {
  imageDragOver.value = false
  const file = e.dataTransfer?.files[0]
  if (file) uploadImageFile(file)
}

function uploadImageFile(file: File) {
  uploadImage(file, (url) => { form.image = url })
}

async function handleAdd() {
  const trimmedName = form.name.trim()
  if (!trimmedName) return
  submitting.value = true
  try {
    await productApi.create({
      name: trimmedName,
      barcode: form.barcode || undefined,
      price: form.price ?? undefined,
      factory: form.factory || undefined,
      image: form.image || undefined,
    })
    showToast('添加成功', 'success')
    Object.assign(form, { name: '', barcode: '', price: 0, factory: '', image: '' })
    queryClient.invalidateQueries({ queryKey: ['products-list'] })
  } catch (err: unknown) {
    showToast(getErrorMessage(err, '添加失败'), 'error')
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.pd-section {
  margin-bottom: 20px;
}
.pd-form-group {
  margin-bottom: 16px;
}
.pd-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  margin-bottom: 6px;
  line-height: 1.4;
}
.pd-input-wrap {
  position: relative;
}
.pd-input-icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-text-secondary);
  font-size: 14px;
  z-index: 10;
  pointer-events: none;
}
.pd-input {
  width: 100%;
  padding: 8px 12px 8px 36px;
  font-size: 14px;
  line-height: 1.5;
  color: var(--color-text);
  background: white;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
  outline: none;
}
.pd-input:focus {
  background: white;
  border-color: var(--color-primary-400);
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.pd-select {
  appearance: none;
  -webkit-appearance: none;
  -moz-appearance: none;
  padding-right: 32px;
  background-image: url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2364748b' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'%3E%3C/polyline%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 12px center;
  background-size: 12px;
  cursor: pointer;
}
.pd-select:disabled { background-color: var(--color-surface, #f8fafc); cursor: not-allowed; }

.pd-btn {
  padding: 7px 14px;
  font-size: 12px;
  font-weight: 600;
  border-radius: 9px;
  border: 2px solid var(--color-border-light);
  background: white;
  transition: background 0.3s ease, border-color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  line-height: 1.4;
}
.pd-btn:hover { transform: translateY(-1px); }
.pd-btn:active { transform: translateY(0); }
.pd-btn:disabled { opacity: 0.4; cursor: not-allowed; transform: none; }
.pd-btn-primary {
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-600));
  color: white;
  border-color: var(--color-primary-500);
}
.pd-btn-primary:hover:not(:disabled) { box-shadow: 0 4px 12px rgba(59,130,246,0.3); }

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
.pd-thumb-preview {
  height: 28px;
  width: 28px;
  object-fit: cover;
  border-radius: 6px;
  border: 1px solid var(--color-border-light);
}
.pd-thumb-remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: none;
  background: rgba(0,0,0,0.4);
  color: white;
  font-size: 9px;
  cursor: pointer;
  margin-left: 2px;
  transition: background 0.2s ease;
}
.pd-thumb-remove:hover { background: rgba(0,0,0,0.7); }
</style>