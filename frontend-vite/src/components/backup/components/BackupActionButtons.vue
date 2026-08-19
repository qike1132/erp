<template>
  <div class="bk-section">
    <div class="bk-section-label">备份备注（可选）</div>
    <div class="bk-form-field">
      <input
        :value="backupRemark"
        type="text"
        class="bk-form-input"
        placeholder="例如：日常备份 / 上线前备份"
        @input="emit('update:backupRemark', ($event.target as HTMLInputElement).value)"
      />
    </div>
    <button
      v-if="backupMode === 'custom'"
      class="bk-action-btn bk-action-primary"
      :disabled="exporting"
      @click="emit('export')"
    >
      <UiLoadingIcon :loading="exporting" icon="download" />
      {{ exporting ? '正在备份...' : '下载备份文件' }}
    </button>
    <button
      v-if="backupMode === 'default'"
      class="bk-action-btn bk-action-primary"
      :disabled="savingToServer"
      @click="emit('save-to-server')"
    >
      <UiLoadingIcon :loading="savingToServer" icon="server" />
      {{ savingToServer ? '正在备份...' : '备份到服务器' }}
    </button>
    <button
      v-if="backupMode === 'default'"
      class="bk-action-btn bk-action-secondary"
      :disabled="savingIncremental"
      @click="emit('save-incremental')"
    >
      <UiLoadingIcon :loading="savingIncremental" icon="layer-group" />
      {{ savingIncremental ? '正在增量备份...' : '增量备份' }}
    </button>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  backupMode: 'custom' | 'default'
  backupRemark: string
  exporting: boolean
  savingToServer: boolean
  savingIncremental: boolean
}>()

const emit = defineEmits<{
  'update:backupRemark': [value: string]
  'export': []
  'save-to-server': []
  'save-incremental': []
}>()
</script>

<style scoped>
.bk-section { margin-bottom: 20px; }
.bk-section-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  margin-bottom: 8px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.bk-form-field {
  margin-bottom: 12px;
}
.bk-form-input {
  width: 100%;
  padding: 8px 12px;
  border: 2px solid var(--color-ocean-light);
  border-radius: var(--radius-input);
  font-size: 14px;
  outline: none;
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
  background: white;
  font-family: inherit;
  color: var(--color-text);
  box-sizing: border-box;
  min-height: 44px;
}
.bk-form-input:focus {
  border-color: var(--color-ocean-deep);
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.bk-form-input::placeholder {
  color: var(--color-text-muted);
  font-size: 14px;
  font-weight: 400;
  opacity: 1;
}
.bk-action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  padding: 12px 18px;
  border: 2px solid var(--color-border-light);
  border-radius: var(--radius-button);
  background: white;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.3s ease, border-color 0.3s ease, transform 0.3s ease, box-shadow 0.3s ease;
}
.bk-action-primary {
  color: var(--color-primary-600);
  background: linear-gradient(135deg, var(--color-primary-50), white);
  border-color: var(--color-primary-200);
}
.bk-action-primary:hover:not(:disabled) {
  background: var(--color-primary-100);
  border-color: var(--color-primary-400);
  transform: translateY(-1px);
  box-shadow: var(--shadow-sm);
}
.bk-action-secondary {
  background: var(--color-neutral-100);
  color: var(--color-neutral-700);
  border: 1px solid var(--color-border-light);
  margin-top: 8px;
}
.bk-action-secondary:hover:not(:disabled) {
  background: var(--color-neutral-200);
}
.bk-action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
}
</style>