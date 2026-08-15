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
          <label class="pjf-label">版师</label>
          <div class="pjf-maker-row">
            <div ref="makerDropdownRef" class="pjf-maker-dropdown">
              <button
                type="button"
                class="pjf-select pjf-maker-trigger"
                @click="makerDropdownOpen = !makerDropdownOpen"
              >
                <span>{{ selectedMakerName || '-- 请选择 --' }}</span>
                <i :class="['fas', makerDropdownOpen ? 'fa-chevron-up' : 'fa-chevron-down']" aria-hidden="true" />
              </button>
              <div v-if="makerDropdownOpen" class="pjf-maker-options">
                <button
                  type="button"
                  :class="['pjf-maker-option', { active: patternMakerId === null }]"
                  @click="selectMaker(null)"
                >
                  <span>-- 请选择 --</span>
                </button>
                <div
                  v-for="pm in patternMakers"
                  :key="pm.id"
                  :class="['pjf-maker-option', { active: patternMakerId === pm.id }]"
                >
                  <button type="button" class="pjf-maker-option-name" @click="selectMaker(pm.id)">
                    <span>{{ pm.name }}</span>
                  </button>
                  <button
                    type="button"
                    class="pjf-maker-del"
                    title="删除"
                    @click.stop="onDeleteMaker(pm.id, pm.name)"
                  >
                    <i class="fas fa-times" aria-hidden="true" />
                  </button>
                </div>
              </div>
            </div>
            <button type="button" class="pjf-role-add" @click="addMakerInputOpen = true">
              <i class="fas fa-plus" aria-hidden="true" />
              添加版师
            </button>
          </div>
          <div v-if="addMakerInputOpen" class="pjf-maker-add-row">
            <input
              v-model="addMakerName"
              class="pjf-input pjf-maker-add-input"
              placeholder="输入版师姓名"
              maxlength="100"
              @keyup.enter="confirmAddMaker"
            />
            <button type="button" class="pjf-role-add" @click="confirmAddMaker">
              确定
            </button>
            <button type="button" class="pjf-maker-cancel" @click="cancelAddMaker">
              取消
            </button>
          </div>
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
              <span class="pjf-upload-hint">支持 JPEG/PNG/WebP，上传前自动压缩（≤1600px）</span>
            </label>
          </div>
        </div>

        <!-- 角色配置（仅新增项目时显示） -->
        <div v-if="!isEditing" class="pjf-field pjf-full">
          <label class="pjf-label">
            角色列表
            <span class="pjf-hint">不添加则仅创建"默认"</span>
          </label>
          <div class="pjf-roles">
            <div v-for="(role, idx) in roleNames" :key="idx" class="pjf-role-row">
              <input
                v-model="roleNames[idx]"
                class="pjf-input pjf-role-input"
                placeholder="角色名称"
                maxlength="100"
              />
              <button
                v-if="roleNames.length > 1"
                type="button"
                class="pjf-role-remove"
                title="移除"
                @click="roleNames.splice(idx, 1)"
              >
                <i class="fas fa-times" aria-hidden="true" />
              </button>
            </div>
            <button type="button" class="pjf-role-add" @click="roleNames.push('')">
              <i class="fas fa-plus" aria-hidden="true" />
              添加角色
            </button>
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
import { reactive, ref, computed, watch, onBeforeUnmount, onMounted } from 'vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiButton from '@/components/ui/UiButton.vue'
import { toast } from '@/composables/useToast'
import type { PatternMaker } from '@/api/patternMaker'
import type { ProjectDetailResponse, ProjectCreateRequest, ProjectUpdateRequest } from '@/api/patternRoom'

const props = defineProps<{
  visible: boolean
  project: ProjectDetailResponse | null
  patternMakers: PatternMaker[]
  patternMakerId: number | null
  submitting: boolean
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  'update:patternMakerId': [value: number | null]
  'submit-create': [data: ProjectCreateRequest]
  'submit-update': [data: ProjectUpdateRequest]
  'upload-image': [file: File]
  'remove-image': []
  'add-pattern-maker': [name: string]
  'delete-pattern-maker': [id: number]
}>()

const isEditing = computed(() => props.project != null)

const form = reactive({
  product_name: '',
  remark: '',
})

/** 角色名称列表（仅新增项目时使用，编辑模式不展示） */
const roleNames = ref<string[]>([''])

/** 内联新增版师 */
const addMakerInputOpen = ref(false)
const addMakerName = ref('')

/** 版师自定义下拉 */
const makerDropdownOpen = ref(false)
const makerDropdownRef = ref<HTMLElement | null>(null)
const selectedMakerName = computed(() => {
  const pm = props.patternMakers.find((m) => m.id === props.patternMakerId)
  return pm?.name ?? ''
})

function selectMaker(id: number | null) {
  emit('update:patternMakerId', id)
  makerDropdownOpen.value = false
}

function onDeleteMaker(id: number, name: string) {
  emit('delete-pattern-maker', id)
  // 如果删除的是当前选中的版师，清空选择
  if (props.patternMakerId === id) {
    emit('update:patternMakerId', null)
  }
  void name
}

/** 点击下拉外部关闭 */
function onDocClick(e: MouseEvent) {
  if (makerDropdownRef.value && !makerDropdownRef.value.contains(e.target as Node)) {
    makerDropdownOpen.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', onDocClick)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
})

const previewUrl = ref<string | null>(null)
const isDragOver = ref(false)

/** 释放本地预览的 ObjectURL，避免 blob 内存泄漏。
 * 仅对 blob: 协议生效，服务端 URL 无需释放。 */
function revokePreview() {
  if (previewUrl.value?.startsWith('blob:')) {
    URL.revokeObjectURL(previewUrl.value)
  }
}

watch(() => props.visible, (val) => {
  if (val) {
    if (props.project) {
      form.product_name = props.project.product_name ?? ''
      form.remark = props.project.remark ?? ''
      // 切换项目前释放上一个本地预览的 blob
      revokePreview()
      previewUrl.value = props.project.product_image_url ?? null
    } else {
      form.product_name = ''
      form.remark = ''
      roleNames.value = ['']
      addMakerInputOpen.value = false
      addMakerName.value = ''
      revokePreview()
      previewUrl.value = null
    }
  }
})

// 弹窗销毁时兜底释放，避免组件卸载残留 blob
onBeforeUnmount(revokePreview)

/** 上传前压缩图片：最长边 ≤1600px，转 WebP（不可用时回退 JPEG）。
 * 手机原图通常 3000-5000px / 数 MB，压缩后体积下降 80%+，
 * 既降低上传带宽，也保证列表缩略图与详情解码流畅。
 * 压缩失败或已是小图时直接返回原文件，不阻断上传。 */
const UPLOAD_MAX_EDGE = 1600
const UPLOAD_QUALITY = 0.82

async function compressImageFile(file: File): Promise<File> {
  // 已是 WebP 且足够小：直接使用，避免无谓重编码
  if (file.type === 'image/webp' && file.size <= 1.5 * 1024 * 1024) return file
  try {
    const bitmap = await createImageBitmap(file)
    const { width, height } = bitmap
    const scale = Math.min(1, UPLOAD_MAX_EDGE / Math.max(width, height))
    // 已是小图且为 JPEG：无需重编码
    if (scale === 1 && file.type === 'image/jpeg' && file.size <= 2 * 1024 * 1024) {
      bitmap.close()
      return file
    }
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(width * scale))
    canvas.height = Math.max(1, Math.round(height * scale))
    const ctx = canvas.getContext('2d')
    if (!ctx) {
      bitmap.close()
      return file
    }
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
    bitmap.close()
    const stem = file.name.replace(/\.(jpe?g|png|webp)$/i, '') || 'image'
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/webp', UPLOAD_QUALITY))
    if (blob && blob.type === 'image/webp') {
      return new File([blob], `${stem}.webp`, { type: 'image/webp' })
    }
    // WebP 不可用时回退 JPEG
    const jpegBlob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', UPLOAD_QUALITY))
    if (jpegBlob) {
      return new File([jpegBlob], `${stem}.jpg`, { type: 'image/jpeg' })
    }
    return file
  } catch (e) {
    console.warn('[ProjectFormDialog] 图片压缩失败，使用原图:', e)
    return file
  }
}

async function applyImageFile(file: File) {
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

  // 上传前压缩（生成小体积 WebP/JPEG），失败时回退原图
  const finalFile = await compressImageFile(file)

  // 释放旧预览的 ObjectURL，避免内存泄漏
  revokePreview()
  previewUrl.value = URL.createObjectURL(finalFile)
  emit('upload-image', finalFile)
}

function onFileChange(e: Event) {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  void applyImageFile(file)
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
  void applyImageFile(file)
}

function removeImage() {
  revokePreview()
  previewUrl.value = null
  emit('remove-image')
}

function confirmAddMaker() {
  const name = addMakerName.value.trim()
  if (!name) {
    toast.warning('请输入版师姓名')
    return
  }
  emit('add-pattern-maker', name)
  addMakerName.value = ''
  addMakerInputOpen.value = false
}

function cancelAddMaker() {
  addMakerInputOpen.value = false
  addMakerName.value = ''
}

function handleSubmit() {
  if (isEditing.value) {
    const data: ProjectUpdateRequest = {
      product_name: form.product_name || null,
      pattern_maker_id: props.patternMakerId,
      remark: form.remark || null,
      version: props.project!.version,
    }
    emit('submit-update', data)
  } else {
    // 过滤空白角色名，去重
    const trimmed = roleNames.value
      .map(n => n.trim())
      .filter(n => n.length > 0)
    const uniqueRoles = Array.from(new Set(trimmed))
    const data: ProjectCreateRequest = {
      product_name: form.product_name,
      pattern_maker_id: props.patternMakerId,
      remark: form.remark || null,
      initial_roles: uniqueRoles.length > 0 ? uniqueRoles : null,
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

.pjf-hint {
  font-size: 11px;
  font-weight: 400;
  color: var(--color-text-muted, #94a3b8);
  margin-left: 6px;
}

.pjf-roles {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.pjf-role-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.pjf-role-input {
  flex: 1;
}

.pjf-role-remove {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 1px solid var(--color-border-light, #e5e7eb);
  border-radius: 8px;
  background: #fff;
  color: var(--color-danger-500, #ef4444);
  cursor: pointer;
  font-size: 11px;
  transition: all 0.15s ease;
}

.pjf-role-remove:hover {
  background: var(--color-danger-50, #fef2f2);
  border-color: var(--color-danger-300, #fca5a5);
}

.pjf-role-add {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1px dashed var(--color-border-light, #e5e7eb);
  border-radius: 8px;
  background: transparent;
  color: var(--color-text-secondary, #6b7280);
  cursor: pointer;
  font-size: 12px;
  font-family: inherit;
  align-self: flex-start;
  transition: all 0.15s ease;
}

.pjf-role-add:hover {
  border-color: var(--color-primary-400, #60a5fa);
  color: var(--color-primary-600, #3b82f6);
  background: var(--color-primary-50, #eff6ff);
}

.pjf-maker-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.pjf-maker-select {
  flex: 1;
  min-width: 0;
}

.pjf-maker-add-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
}

.pjf-maker-add-input {
  flex: 1;
  min-width: 0;
}

.pjf-maker-cancel {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 6px 12px;
  border: 1px solid var(--color-border-light, #e5e7eb);
  border-radius: 8px;
  background: transparent;
  color: var(--color-text-secondary, #6b7280);
  cursor: pointer;
  font-size: 12px;
  font-family: inherit;
  transition: all 0.15s ease;
}

.pjf-maker-cancel:hover {
  border-color: var(--color-danger-300, #fca5a5);
  color: var(--color-danger-500, #ef4444);
  background: var(--color-danger-50, #fef2f2);
}

/* 版师自定义下拉 */
.pjf-maker-dropdown {
  position: relative;
  flex: 1;
  min-width: 0;
}

.pjf-maker-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  cursor: pointer;
}

.pjf-maker-trigger i {
  font-size: 10px;
  color: var(--color-text-secondary, #94a3b8);
  flex-shrink: 0;
  margin-left: 8px;
}

.pjf-maker-options {
  position: absolute;
  top: calc(100% + 2px);
  left: 0;
  right: 0;
  z-index: 50;
  max-height: 240px;
  overflow-y: auto;
  border: 1px solid var(--color-border-light, #e5e7eb);
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.pjf-maker-option {
  display: flex;
  align-items: center;
  width: 100%;
  padding: 0;
  border: none;
  background: #fff;
  transition: background 0.15s;
}

.pjf-maker-option:hover {
  background: var(--color-primary-50, #eff6ff);
}

.pjf-maker-option.active {
  background: var(--color-primary-100, #dbeafe);
}

.pjf-maker-option-name {
  flex: 1;
  min-width: 0;
  padding: 8px 12px;
  border: none;
  background: transparent;
  text-align: left;
  font-size: 13px;
  font-family: inherit;
  color: var(--color-text-primary);
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pjf-maker-del {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  margin-right: 4px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--color-text-muted, #94a3b8);
  cursor: pointer;
  font-size: 12px;
  transition: all 0.15s ease;
}

.pjf-maker-del:hover {
  background: var(--color-danger-50, #fef2f2);
  color: var(--color-danger-500, #ef4444);
}
</style>
