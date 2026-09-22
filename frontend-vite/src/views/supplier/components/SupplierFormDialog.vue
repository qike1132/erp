<template>
  <UiDialog :open="open" :title="mode === 'add' ? '添加新供应商' : '编辑供应商'" max-width-class="max-w-[560px]" @update:open="emit('update:open', $event)">
    <form class="sp-dialog-form" @submit.prevent="emit('submit')">
      <div class="sp-form-field">
        <label class="sp-form-label"><FontAwesomeIcon icon="building" aria-hidden="true" /> 供应商名称 <span class="sp-required">*</span></label>
        <input v-model="form.name" type="text" class="sp-form-input" required :placeholder="mode === 'add' ? '例如：广州面料有限公司' : '请输入供应商名称'" name="supplier-name" autocomplete="off" aria-label="供应商名称" />
      </div>
      <div class="sp-form-row">
        <div class="sp-form-field">
          <label class="sp-form-label"><FontAwesomeIcon icon="user" aria-hidden="true" /> 联系人</label>
          <input v-model="form.contact_person" type="text" class="sp-form-input" :placeholder="mode === 'add' ? '例如：李经理' : ''" name="contact" autocomplete="off" aria-label="联系人" />
        </div>
        <div class="sp-form-field">
          <label class="sp-form-label"><FontAwesomeIcon icon="phone" aria-hidden="true" /> 联系电话</label>
          <input v-model="form.phone" type="text" class="sp-form-input" :placeholder="mode === 'add' ? '例如：13800138000' : ''" name="phone" autocomplete="tel" aria-label="联系电话" />
        </div>
      </div>
      <div class="sp-form-field">
        <label class="sp-form-label"><FontAwesomeIcon icon="location-dot" aria-hidden="true" /> 地址</label>
        <input v-model="form.address" type="text" class="sp-form-input" :placeholder="mode === 'add' ? '例如：广州市白云区' : ''" name="address" autocomplete="off" aria-label="地址" />
      </div>
      <div class="sp-form-field">
        <label class="sp-form-label"><FontAwesomeIcon icon="note-sticky" aria-hidden="true" /> 备注</label>
        <textarea v-model="form.remark" rows="2" maxlength="500" class="sp-form-input" :placeholder="mode === 'add' ? '例如：长期合作供应商' : ''" aria-label="备注" />
      </div>
    </form>
    <template #footer>
      <UiButton variant="ghost" size="sm" @click="emit('update:open', false)">取消</UiButton>
      <UiButton variant="primary" size="sm" :disabled="disabled" @click="emit('submit')">
        <FontAwesomeIcon :icon="mode === 'add' ? 'plus' : 'floppy-disk'" aria-hidden="true" />
        {{ submitting ? (mode === 'add' ? '提交中…' : '保存中…') : (mode === 'add' ? '添加供应商' : '保存') }}
      </UiButton>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import type { SupplierFormData } from '../composables/useSupplier'

const props = defineProps<{
  open: boolean
  mode: 'add' | 'edit'
  submitting: boolean
}>()

// 显式双向绑定：父组件 v-model:form 传入，表单字段就地编辑
const form = defineModel<SupplierFormData>('form', { required: true })

const emit = defineEmits<{
  'update:open': [value: boolean]
  submit: []
}>()

// 名称非空校验 + 提交中禁用，防止校验失败提示后连点重复提交
const disabled = computed(() => !form.value.name?.trim() || props.submitting)
</script>

<style scoped>
.sp-required {
  color: var(--color-danger-500);
  font-weight: 600;
}
.sp-dialog-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.sp-form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.sp-form-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sp-form-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.sp-form-label i {
  margin-right: 4px;
  color: var(--color-primary-500);
  font-size: 11px;
}
.sp-form-input {
  width: 100%;
  padding: 10px 14px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  font-size: 14px;
  outline: none;
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
  background: white;
  font-family: inherit;
  color: var(--color-text);
  box-sizing: border-box;
}
.sp-form-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.sp-form-input:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
textarea.sp-form-input {
  resize: vertical;
  min-height: 60px;
}
</style>