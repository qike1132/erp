<template>
  <UiDialog :open="open" title="驳回原因" max-width-class="max-w-[400px]" @update:open="emit('update:open', $event)">
    <textarea
      v-model="reason"
      rows="3"
      placeholder="请输入驳回原因"
      class="ap-form-textarea"
    />
    <template #footer>
      <button class="ap-action-btn" aria-label="取消 {{ saving ? '提交中…' : '确认驳回' }}" @click="emit('update:open', false)">取消</button>
      <button class="ap-action-btn ap-action-danger" :disabled="saving" :aria-label="saving ? '提交中…' : '确认驳回'" @click="emit('confirm')">
        {{ saving ? '提交中…' : '确认驳回' }}
      </button>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import UiDialog from '@/components/ui/UiDialog.vue'

defineProps<{
  saving: boolean
}>()

const open = defineModel<boolean>('open', { default: false })
const reason = defineModel<string>('reason', { default: '' })

const emit = defineEmits<{
  'update:open': [value: boolean]
  confirm: []
}>()
</script>

<style scoped>
.ap-form-textarea {
  width: 100%;
  padding: 8px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  font-size: 14px;
  transition: border-color 0.3s ease, background 0.3s ease, box-shadow 0.3s ease;
  outline: none;
  font-family: inherit;
  color: var(--color-text);
  resize: none;
  background: white;
}
.ap-form-textarea:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.ap-form-textarea:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.ap-action-btn {
  padding: 5px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  background: white;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.3s ease, border-color 0.3s ease, transform 0.3s ease;
  color: var(--color-text-secondary);
  margin-right: 6px;
}
.ap-action-danger {
  color: var(--color-danger-500);
  border-color: var(--color-danger-200);
}
.ap-action-danger:hover:not(:disabled) {
  background: var(--color-danger-50);
  border-color: var(--color-danger-300);
  transform: translateY(-1px);
}
.ap-action-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>