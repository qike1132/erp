<template>
  <UiDialog v-model:open="dialogOpen" title="确认恢复数据" max-width-class="max-w-[480px]">
    <template #title-icon><FontAwesomeIcon icon="exclamation-triangle" style="color: var(--color-danger-500);" /></template>
    <div class="bk-confirm-body">
      <div class="bk-confirm-icon"><FontAwesomeIcon icon="exclamation-triangle" /></div>
      <div class="bk-confirm-text">
        <p><b>此操作将清除当前所有数据，并从备份文件恢复。</b></p>
        <p>该操作不可撤销，请确保已做好必要准备。</p>
        <p v-if="confirmTarget">{{ confirmTarget }}</p>
      </div>
    </div>
    <template #footer>
      <UiButton variant="ghost" size="sm" @click="dialogOpen = false">取消</UiButton>
      <UiButton variant="danger" size="sm" :disabled="importing || !!restoringFile" @click="emit('confirm')">
        <UiLoadingIcon :loading="importing || !!restoringFile" icon="undo-alt" />
        {{ restorePhase || (importing || restoringFile ? '恢复中...' : '确认恢复') }}
      </UiButton>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
// 确认恢复弹窗（从 BackupView.vue 抽出，模板原样搬移）
import { computed } from 'vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiButton from '@/components/ui/UiButton.vue'

const props = defineProps<{
  open: boolean
  confirmTarget: string
  importing: boolean
  restoringFile: string
  restorePhase: string
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  confirm: []
}>()

// 双向绑定 open（透传给 UiDialog）
const dialogOpen = computed({
  get: () => props.open,
  set: (v: boolean) => emit('update:open', v),
})
</script>

<style scoped>
/* === Confirm Dialog === */
.bk-confirm-body {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}

.bk-confirm-icon {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: var(--color-danger-50);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.bk-confirm-icon i {
  font-size: 22px;
  color: var(--color-danger-500);
}

.bk-confirm-text {
  font-size: 14px;
  color: var(--color-text);
  line-height: 1.6;
}

.bk-confirm-text p {
  margin: 0 0 6px;
}

.bk-confirm-text p:last-child {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: 13px;
}
</style>
