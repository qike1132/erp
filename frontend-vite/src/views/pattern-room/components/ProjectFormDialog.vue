<template>
  <UiDialog
    :open="visible"
    :title="isEditing ? '编辑打样项目' : '新增打样项目'"
    max-width="500px"
    @update:open="$emit('update:visible', $event)"
  >
    <div class="pjf-body">
      <div class="pjf-grid">
        <div class="pjf-field">
          <label class="pjf-label">产品名称 <span class="pjf-required">*</span></label>
          <input
            v-model="form.product_name"
            class="pjf-input"
            placeholder="请输入产品名称"
          />
        </div>

        <div class="pjf-field">
          <label class="pjf-label">客户</label>
          <select v-model="form.customer_id" class="pjf-select">
            <option :value="null">-- 请选择 --</option>
            <option v-for="c in customers" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
        </div>

        <div class="pjf-field pjf-full">
          <label class="pjf-label">备注</label>
          <textarea v-model="form.remark" class="pjf-textarea" rows="3" placeholder="项目备注..." />
        </div>

        <!-- 产品图片上传 -->
        <div class="pjf-field pjf-full">
          <label class="pjf-label">产品图片</label>
          <div class="pjf-image-section">
            <div v-if="previewUrl" class="pjf-image-preview">
              <img :src="previewUrl" alt="预览" class="pjf-img" />
              <button class="pjf-img-remove" aria-label="移除图片" @click="removeImage">&times;</button>
            </div>
            <label
              v-else
              :class="['pjf-upload-area', { 'pjf-upload-area--dragover': isDragOver }]"
              @dragover.prevent="onDragOver"
              @dragleave.prevent="onDragLeave"
              @drop.prevent="onDrop"
            >
              <input type="file" accept="image/jpeg,image/png,image/webp" class="pjf-file-input" @change="onFileChange" />
              <i class="fas fa-cloud-upload-alt" aria-hidden="true" />
              <span>点击或拖拽图片到此处上传</span>
              <span class="pjf-upload-hint">支持 JPEG/PNG/WebP，≤10MB</span>
            </label>
          </div>
        </div>
      </div>
    </div>
    <template #footer>
      <div class="pjf-footer">
        <UiButton variant="ghost" @click="$emit('update:visible', false)">取消</UiButton>
        <UiButton variant="primary" :loading="submitting" :disabled="!form.product_name.trim()" @click="handleSubmit">
          {{ isEditing ? '保存' : '创建' }}
        </UiButton>
      </div>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import { reactive, ref, computed, watch } from 'vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiButton from '@/components/ui/UiButton.vue'
import { toast } from '@/composables/useToast'
import type { Customer } from '@/types'
import type { ProjectDetailResponse, ProjectCreateRequest, ProjectUpdateRequest } from '@/api/patternRoom'

const props = defineProps<{
  visible: boolean
  project: ProjectDetailResponse | null
  customers: Customer[]
  submitting: boolean
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  'submit-create': [data: ProjectCreateRequest]
  'submit-update': [data: ProjectUpdateRequest]
  'upload-image': [file: File]
  'remove-image': []
}>()

const isEditing = computed(() => props.project != null)

const form = reactive({
  product_name: '',
  customer_id: null as number | null,
  remark: '',
})

const previewUrl = ref<string | null>(null)
const isDragOver = ref(false)

watch(() => props.visible, (val) => {
  if (val) {
    if (props.project) {
      form.product_name = props.project.product_name ?? ''
      form.customer_id = props.project.customer_id ?? null
      form.remark = props.project.remark ?? ''
      previewUrl.value = props.project.product_image_url ?? null
    } else {
      form.product_name = ''
      form.customer_id = null
      form.remark = ''
      previewUrl.value = null
    }
  }
})

function applyImageFile(file: File) {
  // 校验
  const allowed = ['image/jpeg', 'image/png', 'image/webp']
  if (!allowed.includes(file.type)) {
    toast.warning('仅支持 JPEG / PNG / WebP 格式')
    return
  }
  if (file.size > 10 * 1024 * 1024) {
    toast.warning('图片大小不能超过 10MB')
    return
  }

  // 释放旧预览的 ObjectURL，避免内存泄漏
  if (previewUrl.value?.startsWith('blob:')) {
    URL.revokeObjectURL(previewUrl.value)
  }
  previewUrl.value = URL.createObjectURL(file)
  emit('upload-image', file)
}

function onFileChange(e: Event) {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  applyImageFile(file)
  target.value = ''
}

function onDragOver(e: DragEvent) {
  // 仅响应包含文件的拖拽
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
  applyImageFile(file)
}

function removeImage() {
  previewUrl.value = null
  emit('remove-image')
}

function handleSubmit() {
  if (isEditing.value) {
    const data: ProjectUpdateRequest = {
      product_name: form.product_name || null,
      customer_id: form.customer_id,
      remark: form.remark || null,
      version: props.project!.version,
    }
    emit('submit-update', data)
  } else {
    const data: ProjectCreateRequest = {
      product_name: form.product_name,
      customer_id: form.customer_id,
      remark: form.remark || null,
    }
    emit('submit-create', data)
  }
}
</script>

<style scoped>
.pjf-body {
  padding: 16px 0;
}
.pjf-grid {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.pjf-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.pjf-full {
  grid-column: 1 / -1;
}
.pjf-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary);
}
.pjf-required {
  color: #ef4444;
}
.pjf-input, .pjf-select, .pjf-textarea {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--color-border-light);
  border-radius: 8px;
  font-size: 13px;
  font-family: inherit;
  background: var(--color-surface);
  color: var(--color-text-primary);
  outline: none;
  transition: border-color 0.2s;
  box-sizing: border-box;
}
.pjf-input:focus, .pjf-select:focus, .pjf-textarea:focus {
  border-color: var(--color-primary-500);
}
.pjf-textarea {
  resize: vertical;
}
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
.pjf-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 8px;
}
</style>
