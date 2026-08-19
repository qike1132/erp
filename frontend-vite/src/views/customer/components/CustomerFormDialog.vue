<template>
  <UiDialog :open="open" :title="mode === 'add' ? '新建客户' : '编辑客户'" @update:open="emit('update:open', $event)">
    <form @submit.prevent="emit('submit')">
      <div class="cu-form-group">
        <label>客户名称 <span class="cu-required">*</span></label>
        <input v-model="form.name" class="cu-form-input" required placeholder="请输入客户名称" name="customer-name" autocomplete="off" aria-label="请输入客户名称" />
      </div>
      <div class="cu-form-grid">
        <div class="cu-form-group"><label>联系人</label><input v-model="form.contact" class="cu-form-input" placeholder="联系人姓名" name="contact" autocomplete="off" aria-label="联系人姓名" /></div>
        <div class="cu-form-group"><label>联系电话</label><input v-model="form.phone" class="cu-form-input" placeholder="联系电话" name="phone" autocomplete="tel" aria-label="联系电话" /></div>
      </div>
      <div class="cu-form-group"><label>地址</label><input v-model="form.address" class="cu-form-input" placeholder="详细地址" name="address" autocomplete="off" aria-label="详细地址" /></div>
      <div class="cu-form-group">
        <label>备注</label>
        <textarea v-model="form.note" rows="3" placeholder="选填" class="cu-form-textarea" style="resize: none" aria-label="选填" />
      </div>
    </form>
    <template #footer>
      <button class="cu-action-btn" @click="emit('update:open', false)" aria-label="取消">取消</button>
      <button class="cu-action-btn cu-action-primary" :disabled="submitting" @click="emit('submit')" :aria-label="submitting ? '提交中…' : mode === 'add' ? '创建' : '保存修改'">
        {{ submitting ? '提交中…' : mode === 'add' ? '创建' : '保存修改' }}
      </button>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import UiDialog from '@/components/ui/UiDialog.vue'
import type { CustomerFormData } from '../composables/useCustomer'

defineProps<{
  open: boolean
  mode: 'add' | 'edit'
  submitting: boolean
  form: CustomerFormData
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  submit: []
}>()
</script>

<style scoped>
.cu-form-group {
  margin-bottom: 14px;
}
.cu-form-group label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--color-text-secondary);
  margin-bottom: 6px;
}
.cu-required { color: var(--color-danger-500); }
.cu-form-input {
  width: 100%;
  padding: 8px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  font-size: 14px;
  transition: border-color 0.3s ease, background 0.3s ease, box-shadow 0.3s ease;
  outline: none;
  font-family: inherit;
  color: var(--color-text);
  background: white;
}
.cu-form-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.cu-form-input:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.cu-form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.cu-form-textarea {
  width: 100%;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  padding: 8px 12px;
  font-size: 14px;
  outline: none;
  transition: border-color 0.3s ease, background 0.3s ease, box-shadow 0.3s ease;
  font-family: inherit;
  color: var(--color-text);
}
.cu-form-textarea:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.cu-form-textarea:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.cu-action-btn {
  border-radius: 9px;
  padding: 7px 14px;
  border: 2px solid var(--color-border-light);
  background: white;
  font-size: 12px;
  font-weight: 600;
  transition: background 0.3s ease, border-color 0.3s ease, transform 0.3s ease;
  cursor: pointer;
  color: var(--color-text);
  font-family: inherit;
}
.cu-action-btn:hover {
  transform: translateY(-1px);
}
.cu-action-primary {
  color: var(--color-primary-600);
}
.cu-action-primary:hover {
  background: var(--color-primary-50);
  border-color: var(--color-primary-300);
}
.cu-action-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  transform: none;
}
@media (max-width: 900px) {
  .cu-form-grid { grid-template-columns: 1fr; }
}
</style>
