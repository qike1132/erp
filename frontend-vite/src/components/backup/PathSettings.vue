<template>
  <div class="ps-card">
    <!-- 2026-10-17 审计 AUD-08：backup_settings 表未接线，清理/备份实际读环境变量。
         知情假功能比无功能更危险，这里明确标注并禁用保存。 -->
    <div class="ps-warn">
      当前版本备份目录由环境变量 <code>BACKUP_DIR</code> 决定，此处保存不会生效（设置接线待后续专项）。
      实际生效目录：<code>{{ settings?.effective_backup_dir || '未知（设置未加载或后端未返回）' }}</code>
    </div>
    <div class="ps-radio-row">
      <label class="ps-radio">
        <input type="radio" value="default" :checked="mode === 'default'" @change="mode = 'default'" />
        <span>默认系统路径</span>
      </label>
      <div class="ps-path mono">{{ settings?.default_backup_dir || 'backups/server' }}</div>
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
      <button class="ps-btn ps-btn-outline" @click="handleValidate">校验路径</button>
      <button class="ps-btn ps-btn-primary" :disabled="saving || !settingsWired" title="当前版本设置未接线，保存不生效" @click="handleSave">{{ saving ? '保存中...' : '保存设置' }}</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { BackupSettings } from '@/api/backup'

const props = defineProps<{
  settings: BackupSettings | null
  saving?: boolean
  onValidate: (path: string) => Promise<{ valid: boolean; error?: string } | void>
  onSave: (path: string) => void
}>()

const mode = ref<'default' | 'custom'>('default')
const customPath = ref('')
// 设置表尚未接线（AUD-08）：保存按钮禁用，避免用户误以为修改生效。
// 2026-10-18 OCR 评审：由后端 effective_source 驱动，接线后自动放开。
// fail-closed：只有后端明确返回非 env 来源才认为已接线
const settingsWired = computed(
  () => !!props.settings?.effective_source && props.settings.effective_source !== 'env',
)
const feedback = ref<{ tone: string; text: string }>({ tone: '', text: '' })

// 加载设置后同步单选状态:当前生效路径与默认一致 → default,否则回显自定义路径
watch(() => props.settings, (s) => {
  if (!s) return
  const dft = s.default_backup_dir || ''
  const usingDefault = !s.backup_dir || !dft || s.backup_dir === dft
  mode.value = usingDefault ? 'default' : 'custom'
  if (!usingDefault) customPath.value = s.backup_dir
  feedback.value = { tone: '', text: '' }
}, { immediate: true })

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

// 注意：局部处理器不得与 props 同名（props.onValidate / props.onSave）。
// 同名会让模板 `@click` 的解析产生歧义（vue/no-dupe-keys），故一律用 handle* 前缀。
async function handleValidate() {
  const v = customPath.value.trim()
  if (!v) { feedback.value = { tone: 'error', text: '请输入自定义路径' }; return }
  const res = await props.onValidate(v)
  feedback.value = res && !res.valid ? { tone: 'error', text: res.error || '路径不合法' } : { tone: 'ok', text: '路径可写' }
}

function handleSave() {
  if (mode.value === 'default') { props.onSave(''); return }
  const v = customPath.value.trim()
  if (!v) { feedback.value = { tone: 'error', text: '请输入自定义路径' }; return }
  props.onSave(v)
}
</script>

<style scoped>
.ps-card { border: 1px solid var(--color-border-light); border-radius: var(--radius-md, 14px); background: #ffffff; padding: 24px; box-shadow: 0 1px 3px rgba(0,0,0,.04), 0 4px 12px rgba(0,0,0,.06); }
.ps-warn { margin-bottom: 12px; padding: 10px 12px; border-radius: var(--radius-input, 12px); background: #fff7e6; border: 1px solid #ffd591; color: #ad6800; font-size: 13px; line-height: 1.6; }
.ps-warn code { font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace; background: rgba(0,0,0,.04); padding: 1px 4px; border-radius: 4px; }
.ps-radio-row { padding: 8px 0; }
.ps-radio { display: flex; align-items: center; gap: 8px; font-size: 14px; color: var(--color-text); }
.ps-radio input { accent-color: var(--color-primary-600); }
.ps-path { margin-top: 8px; margin-left: 22px; background: var(--color-slate-100, #f1f5f9); border-radius: var(--radius-input, 12px); padding: 10px 12px; font-size: 13px; color: var(--color-text-secondary); overflow-x: auto; white-space: nowrap; }
.ps-custom { margin-left: 22px; margin-top: 8px; }
.ps-input { width: 100%; height: 36px; padding: 0 12px; border: 1px solid var(--color-border-light); border-radius: var(--radius-input, 12px); font-size: 14px; font-family: inherit; color: var(--color-text); background: #ffffff; transition: border-color 0.2s ease, box-shadow 0.2s ease; }
.ps-input:focus { outline: none; border-color: var(--color-primary-300); box-shadow: 0 0 0 3px var(--color-primary-50); }
.ps-feedback { margin-top: 6px; font-size: 12px; }
.ps-feedback.ok { color: var(--color-success-500); }
.ps-feedback.error { color: var(--color-danger-500); }
.mono { font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace; }
.ps-actions { display: flex; gap: 12px; margin-top: 16px; }
.ps-btn { display: inline-flex; align-items: center; height: 36px; padding: 0 16px; border: 2px solid transparent; border-radius: var(--radius-button, 14px); font-size: 13px; font-weight: 600; font-family: inherit; cursor: pointer; transition: background 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease, border-color 0.2s ease, color 0.2s ease; }
.ps-btn-primary { background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700)); color: #fff; box-shadow: 0 4px 12px rgba(91, 141, 239, 0.24); }
.ps-btn-primary:disabled { background: var(--color-border-light); color: var(--color-text-muted); cursor: not-allowed; box-shadow: none; }
.ps-btn-primary:hover:not(:disabled) { box-shadow: 0 6px 18px rgba(91, 141, 239, 0.32); transform: translateY(-1px); }
.ps-btn-outline { background: #ffffff; border-color: var(--color-border-light); color: var(--color-primary-600); }
.ps-btn-outline:hover { border-color: var(--color-primary-300); background: var(--color-primary-50); color: var(--color-primary-700); }
</style>