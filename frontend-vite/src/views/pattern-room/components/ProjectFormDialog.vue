<template>
  <UiDialog
    :open="visible"
    :title="isEditing ? '编辑打样项目' : '新增打样项目'"
    max-width="500px"
    @update:open="$emit('update:visible', $event)"
  >
    <div class="pjf-body">
      <div class="pjf-grid">
        <UiFormField v-slot="field" label="产品名称" required>
          <input
            v-bind="field"
            v-model="form.product_name"
            class="pjf-input"
            placeholder="请输入产品名称"
            maxlength="200"
          />
        </UiFormField>

        <div class="pjf-field">
          <!-- 版师是自绘下拉（非表单控件），用 <span id> + aria-labelledby 建立关联。
               原来这里是 <label> 却没有 for，属于无效关联。 -->
          <span id="pjf-maker-label" class="pjf-label">版师</span>
          <DialogMakerSelect
            :pattern-makers="patternMakers"
            :pattern-maker-id="patternMakerId"
            labelledby="pjf-maker-label"
            @update:pattern-maker-id="$emit('update:patternMakerId', $event)"
            @add-pattern-maker="$emit('add-pattern-maker', $event)"
            @delete-pattern-maker="$emit('delete-pattern-maker', $event)"
          />
        </div>

        <UiFormField v-slot="field" label="备注" class="pjf-full">
          <textarea
            v-bind="field"
            v-model="form.remark"
            class="pjf-textarea"
            rows="3"
            maxlength="2000"
            placeholder="项目备注..."
          />
        </UiFormField>

        <div ref="imageZoneRef" class="pjf-field pjf-full pjf-image-zone">
          <!-- 复合区域（预览 / 上传 / 移除多个控件），标签只作视觉分组说明，
               控件自身的可访问名由 DialogImageUpload 内部提供 -->
          <span class="pjf-label">产品图片</span>
          <DialogImageUpload
            :preview-url="previewUrl"
            :paste-flash="pasteFlash"
            :uploading="processing"
            @upload-file="applyImageFile"
            @remove="removeImage"
          />
        </div>

        <div v-if="!isEditing" class="pjf-field pjf-full">
          <span class="pjf-label">
            角色列表
            <span class="pjf-hint">不添加则仅创建"默认"</span>
          </span>
          <DialogRoleEditor v-model="roleNames" />
        </div>
      </div>
    </div>
    <template #footer>
      <div class="pjf-footer">
        <UiButton variant="ghost" @click="$emit('update:visible', false)">取消</UiButton>
        <!-- AUD-10：UiButton 无 loading prop，:loading 是死属性——提交在途用
             :disabled 收口（双击重复创建的守卫补在 useSamplingProject 三函数）。 -->
        <UiButton variant="primary" :disabled="submitting || !form.product_name.trim()" @click="handleSubmit">
          {{ isEditing ? '保存' : '创建' }}
        </UiButton>
      </div>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import { reactive, ref, computed, watch, onBeforeUnmount } from 'vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiFormField from '@/components/ui/UiFormField.vue'
import DialogMakerSelect from './DialogMakerSelect.vue'
import DialogImageUpload from './DialogImageUpload.vue'
import DialogRoleEditor from './DialogRoleEditor.vue'
import type { PatternMaker } from '@/api/patternMaker'
import type { ProjectDetailResponse, ProjectCreateRequest, ProjectUpdateRequest } from '@/api/patternRoom'
import { useFormImageUpload } from '../composables/useFormImageUpload'
import { useImagePaste } from '@/composables/useImagePaste'

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

const roleNames = ref<string[]>([''])

/** 编辑模式下是否移除了已有产品图片（提交时 product_image_file_id 显式传 null，后端清除旧图） */
const imageRemoved = ref(false)

const { previewUrl, processing, setPreview, applyImageFile, removeImage } = useFormImageUpload(
  (file) => {
    imageRemoved.value = false
    emit('upload-image', file)
  },
  () => {
    imageRemoved.value = true
    emit('remove-image')
  },
)

/** 图片区容器（始终渲染）作为粘贴热区：预览分支下虚线框不存在，不能以它为热区 */
const imageZoneRef = ref<HTMLElement | null>(null)
const pasteFlash = ref(false)
let pasteFlashTimer: ReturnType<typeof setTimeout> | undefined

/** 粘贴命中时复用拖拽高亮，给出「已接收」的即时反馈 */
function flashPasteFeedback() {
  pasteFlash.value = true
  clearTimeout(pasteFlashTimer)
  pasteFlashTimer = setTimeout(() => { pasteFlash.value = false }, 600)
}

// 弹窗优先级高于底层表单/列表：弹窗打开时只有本弹窗响应粘贴
useImagePaste({
  target: imageZoneRef,
  onFile: (file) => {
    flashPasteFeedback()
    void applyImageFile(file)
  },
  enabled: () => props.visible && !props.submitting,
  priority: 10,
})

onBeforeUnmount(() => clearTimeout(pasteFlashTimer))

watch(() => props.visible, (val) => {
  if (val) {
    imageRemoved.value = false
    if (props.project) {
      form.product_name = props.project.product_name ?? ''
      form.remark = props.project.remark ?? ''
      setPreview(props.project.product_image_url ?? null)
    } else {
      form.product_name = ''
      form.remark = ''
      roleNames.value = ['']
      setPreview(null)
    }
  }
})

function handleSubmit() {
  if (isEditing.value) {
    const data: ProjectUpdateRequest = {
      product_name: form.product_name || null,
      // 三态：null = 清空版师（用户选回"请选择"）；有值 = 设置/保持
      pattern_maker_id: props.patternMakerId,
      // 空串即"清空备注"（后端 None 语义为不修改）
      remark: form.remark,
      // 三态：undefined（序列化时丢弃，不修改）或 null（清空图片）
      ...(imageRemoved.value ? { product_image_file_id: null } : {}),
      version: props.project!.version,
    }
    emit('submit-update', data)
  } else {
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
/* .pjf-required 已移除：必填 * 由 UiFormField 渲染（带 aria-hidden，避免读屏念「星号」） */
.pjf-input, .pjf-textarea {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--color-border-light);
  border-radius: 8px;
  font-size: 13px;
  font-family: inherit;
  background: var(--color-surface);
  color: var(--color-text-primary);
  transition: border-color 0.2s;
  box-sizing: border-box;
}
/* 不再写 outline: none —— 那会盖掉全局 :focus-visible 焦点环（审查 A11Y-10） */
.pjf-input:focus-visible, .pjf-textarea:focus-visible {
  border-color: var(--color-primary-500);
}
.pjf-textarea {
  resize: vertical;
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
</style>
