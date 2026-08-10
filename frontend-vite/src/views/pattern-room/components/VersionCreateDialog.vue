<template>
  <UiDialog
    :open="open"
    :title="'创建新版本'"
    max-width="440px"
    @update:open="$emit('update:open', $event)"
  >
    <div class="vc-body">
      <p class="vc-info">
        将基于当前项目的最新版本 <strong>{{ currentVersion }}</strong> 创建新版本号，并快照当前所有部位布料信息。
      </p>
      <div class="vc-field">
        <label class="vc-label">变更原因（可选）</label>
        <textarea
          v-model="reason"
          class="vc-textarea"
          rows="3"
          placeholder="请描述本次版本变更的原因..."
        />
      </div>
    </div>
    <template #footer>
      <div class="vc-footer">
        <UiButton variant="ghost" @click="$emit('update:open', false)">取消</UiButton>
        <UiButton variant="primary" :loading="submitting" @click="handleConfirm">确认创建</UiButton>
      </div>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiButton from '@/components/ui/UiButton.vue'

const props = defineProps<{
  open: boolean
  currentVersion: string
  submitting: boolean
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  confirm: [reason: string | null]
}>()

const reason = ref('')

function handleConfirm() {
  emit('confirm', reason.value || null)
}
</script>

<style scoped>
.vc-body {
  padding: 20px 0;
}
.vc-info {
  font-size: 13px;
  color: var(--color-text-secondary);
  margin: 0 0 16px;
  line-height: 1.5;
}
.vc-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.vc-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary);
}
.vc-textarea {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--color-border-light);
  border-radius: 8px;
  font-size: 13px;
  font-family: inherit;
  resize: vertical;
  background: var(--color-surface);
  color: var(--color-text-primary);
  outline: none;
  transition: border-color 0.2s;
  box-sizing: border-box;
}
.vc-textarea:focus {
  border-color: var(--color-primary-500);
}
.vc-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 8px;
}
</style>
