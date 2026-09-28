<template>
  <UiDialog v-model:open="openModel" title="编辑暂存出货" max-width-class="max-w-[500px]">
    <div class="dialog-form">
      <div class="form-field">
        <label class="form-label">出货时间</label>
        <UiDatePicker v-model="form.date" style="width: 100%" />
      </div>
      <div class="form-field">
        <label class="form-label">客户名称</label>
        <UiSelect v-model="form.customer" :options="customerOptions" />
      </div>
      <div class="form-field">
        <label class="form-label">产品名称</label>
        <UiInput :model-value="form.productName" disabled />
      </div>
      <div class="form-field">
        <label class="form-label">出货数量</label>
        <input v-model.number="form.quantity" type="number" class="form-input" min="1" step="1" name="quantity" autocomplete="off" aria-label="出货数量" />
      </div>
      <div class="form-field">
        <label class="form-label">备注</label>
        <textarea v-model="form.note" class="form-input" rows="2" aria-label="备注" />
      </div>
    </div>
    <template #footer>
      <UiButton variant="outline" @click="openModel = false">取消</UiButton>
      <UiButton variant="primary" @click="emit('save')">保存</UiButton>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import UiInput from '@/components/ui/UiInput.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiDialog from '@/components/ui/UiDialog.vue'

interface EditStagedForm {
  customer: string
  date: string
  productName: string
  quantity: number
  note: string
}

defineProps<{
  customerOptions: { value: string; label: string }[]
}>()

const openModel = defineModel<boolean>('open', { default: false })

const form = defineModel<EditStagedForm>('form', { required: true })

const emit = defineEmits<{
  save: []
}>()
</script>

<style scoped>
.dialog-form {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.form-field { margin-bottom: 10px; }
.form-label {
  display: block;
  font-weight: 500;
  font-size: 13px;
  color: var(--color-text-secondary);
  margin-bottom: 4px;
}
.form-input {
  width: 100%;
  padding: 8px 12px;
  font-size: 14px;
  line-height: 1.5;
  color: var(--color-text);
  background: white;
  border: 2px solid var(--color-border, #cbd5e1);
  border-radius: var(--radius-input, 12px);
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
  outline: none;
  min-height: 40px;
  box-sizing: border-box;
  font-family: inherit;
  -moz-appearance: textfield;
}
.form-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.form-input::-webkit-inner-spin-button,
.form-input::-webkit-outer-spin-button { opacity: 1; }
.form-input:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
textarea.form-input { resize: vertical; }
</style>
