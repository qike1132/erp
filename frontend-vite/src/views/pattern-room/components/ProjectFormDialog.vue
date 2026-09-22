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
            maxlength="200"
          />
        </div>

        <div class="pjf-field">
          <label class="pjf-label">版师</label>
          <DialogMakerSelect
            :pattern-makers="patternMakers"
            :pattern-maker-id="patternMakerId"
            @update:pattern-maker-id="$emit('update:patternMakerId', $event)"
            @add-pattern-maker="$emit('add-pattern-maker', $event)"
            @delete-pattern-maker="$emit('delete-pattern-maker', $event)"
          />
        </div>

        <div class="pjf-field pjf-full">
          <label class="pjf-label">备注</label>
          <textarea v-model="form.remark" class="pjf-textarea" rows="3" maxlength="2000" placeholder="项目备注..." aria-label="项目备注..." />
        </div>

        <div class="pjf-field pjf-full">
          <label class="pjf-label">产品图片</label>
          <DialogImageUpload
            :preview-url="previewUrl"
            @upload-file="applyImageFile"
            @remove="removeImage"
          />
        </div>

        <div v-if="!isEditing" class="pjf-field pjf-full">
          <label class="pjf-label">
            角色列表
            <span class="pjf-hint">不添加则仅创建"默认"</span>
          </label>
          <DialogRoleEditor v-model="roleNames" />
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
import DialogMakerSelect from './DialogMakerSelect.vue'
import DialogImageUpload from './DialogImageUpload.vue'
import DialogRoleEditor from './DialogRoleEditor.vue'
import type { PatternMaker } from '@/api/patternMaker'
import type { ProjectDetailResponse, ProjectCreateRequest, ProjectUpdateRequest } from '@/api/patternRoom'
import { useFormImageUpload } from '../composables/useFormImageUpload'

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

/** 编辑模式下是否移除了已有产品图片（提交时带 clear_image，后端清除旧图） */
const imageRemoved = ref(false)

const { previewUrl, setPreview, applyImageFile, removeImage } = useFormImageUpload(
  (file) => {
    imageRemoved.value = false
    emit('upload-image', file)
  },
  () => {
    imageRemoved.value = true
    emit('remove-image')
  },
)

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
      pattern_maker_id: props.patternMakerId,
      // 用户将版师选回"请选择"时需显式清除后端关联
      clear_pattern_maker: props.patternMakerId === null,
      // 空串即"清空备注"（后端 None 语义为不修改）
      remark: form.remark,
      clear_image: imageRemoved.value,
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
.pjf-required {
  color: #ef4444;
}
.pjf-input, .pjf-textarea {
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
.pjf-input:focus, .pjf-textarea:focus {
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
