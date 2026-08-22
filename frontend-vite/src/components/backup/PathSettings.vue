<template>
  <div class="ps-card">
    <div class="ps-radio-row">
      <label class="ps-radio">
        <input type="radio" value="default" :checked="mode === 'default'" @change="mode = 'default'" />
        <span>默认系统路径</span>
      </label>
      <div class="ps-path mono">{{ settings?.backup_dir || 'backups/server' }}</div>
    </div>
    <div class="ps-radio-row">
      <label class="ps-radio">
        <input type="radio" value="custom" :checked="mode === 'custom'" @change="mode = 'custom'" />
        <span>自定义路径</span>
      </label>
      <div v-if="mode === 'custom'" class="ps-custom">
        <input v-model="customPath" class="ps-input mono" placeholder="D:\erp_data\backups\custom" @input="onPathInput" />
        <div class="ps-feedback" :class="feedback.tone">{{ feedback.text }}</div>
      </div>
    </div>
    <div class="ps-actions">
      <button class="ps-btn ps-btn-outline" @click="onValidate">校验路径</button>
      <button class="ps-btn ps-btn-primary" :disabled="saving" @click="onSave">{{ saving ? '保存中...' : '保存设置' }}</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import type { BackupSettings } from '@/api/backup'

const props = defineProps<{
  settings: BackupSettings | null
  saving?: boolean
  onValidate: (path: string) => Promise<{ valid: boolean; error?: string } | void>
  onSave: (path: string) => void
}>()

const mode = ref<'default' | 'custom'>('default')
const customPath = ref('')
const feedback = ref<{ tone: string; text: string }>({ tone: '', text: '' })

watch(mode, (m) => {
  if (m === 'default') customPath.value = ''
  feedback.value = { tone: '', text: '' }
})

async function onPathInput() {
  const v = customPath.value.trim()
  if (!v) { feedback.value = { tone: '', text: '' }; return }
  const res = await props.onValidate(v)
  if (res && !res.valid) feedback.value = { tone: 'error', text: res.error || '路径不合法' }
  else if (res && res.valid) feedback.value = { tone: 'ok', text: '路径可写' }
}

async function onValidate() {
  const v = customPath.value.trim()
  if (!v) { feedback.value = { tone: 'error', text: '请输入自定义路径' }; return }
  const res = await props.onValidate(v)
  feedback.value = res && !res.valid ? { tone: 'error', text: res.error || '路径不合法' } : { tone: 'ok', text: '路径可写' }
}

function onSave() {
  if (mode.value === 'default') { props.onSave(''); return }
  const v = customPath.value.trim()
  if (!v) { feedback.value = { tone: 'error', text: '请输入自定义路径' }; return }
  props.onSave(v)
}
</script>

<style scoped>
.ps-card { border: 1px solid var(--color-border, #e5e6eb); border-radius: 8px; background: var(--color-surface, #fff); padding: 20px; }
.ps-radio-row { padding: 8px 0; }
.ps-radio { display: flex; align-items: center; gap: 8px; font-size: 14px; }
.ps-radio input { accent-color: var(--color-primary, #2f7bff); }
.ps-path { margin-top: 8px; margin-left: 22px; background: var(--color-surface-muted, #f2f3f5); border-radius: 6px; padding: 8px 12px; font-size: 13px; color: var(--color-text-secondary, #4e5969); overflow-x: auto; white-space: nowrap; }
.ps-custom { margin-left: 22px; margin-top: 8px; }
.ps-input { width: 100%; height: 32px; padding: 0 12px; border: 1px solid var(--color-border-strong, #c9cdd4); border-radius: 6px; font-size: 14px; }
.ps-feedback { margin-top: 6px; font-size: 12px; }
.ps-feedback.ok { color: var(--color-success, #10b981); }
.ps-feedback.error { color: var(--color-danger, #ef4444); }
.mono { font-family: var(--font-mono, Consolas, monospace); }
.ps-actions { display: flex; gap: 12px; margin-top: 16px; }
.ps-btn { height: 32px; padding: 0 16px; border-radius: 6px; font-size: 14px; cursor: pointer; border: 1px solid transparent; }
.ps-btn-primary { background: var(--color-primary, #2f7bff); color: #fff; }
.ps-btn-primary:disabled { background: var(--color-surface-muted, #f2f3f5); color: var(--color-text-disabled, #c9cdd4); cursor: not-allowed; }
.ps-btn-outline { background: transparent; border-color: var(--color-border, #e5e6eb); color: var(--color-text-secondary, #4e5969); }
</style>