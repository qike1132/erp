<template>
  <div class="ba-card">
    <div class="ba-actions">
      <button class="ba-btn ba-btn-primary" :disabled="busy || !!task?.taskId" @click="handleFull">
        一键全量备份
      </button>
      <button class="ba-adv-toggle" @click="advancedOpen = !advancedOpen">
        {{ advancedOpen ? '收起选项' : '高级选项' }}
      </button>
      <span v-if="busy" class="ba-mutex-hint">有任务执行中</span>
      <!-- P1-20（2026-11-17 审计）：加密状态必须一眼可见 —— 否则总开关关闭时页面照样
           显示密码框，运维以为在产出加密包，实际是明文。状态未知时不渲染徽标，
           绝不把「没读到」说成「已开启」。 -->
      <span
        v-if="encryptionKnown"
        class="ba-enc-badge"
        :class="encryptionEnabled ? 'ba-enc-on' : 'ba-enc-off'"
        data-testid="ba-enc-state"
      >
        {{ encryptionEnabled ? '备份加密已开启' : '加密已关闭 · 备份为明文' }}
      </span>
    </div>

    <div v-if="advancedOpen" class="ba-advanced">
      <p class="ba-adv-hint" :class="{ 'ba-adv-warn': !encryptionEnabled }">{{ encryptionHint }}</p>
      <!-- P1-20：总开关关闭时后端会**静默**忽略 encrypt=true，此时密码框只会诱导运维
           去配一个无效密码 —— 直接不渲染，改由上面的说明文字讲清现状。 -->
      <div v-if="encryptionEnabled" class="ba-field">
        <label class="ba-field-label" for="ba-enc-pw">加密密码（可选）</label>
        <input id="ba-enc-pw" v-model="password" type="password" class="ba-input" autocomplete="new-password"
               placeholder="留空则用服务端配置的密码；两者都没有时后端会拒绝（绝不生成随机密钥）"
        />
      </div>
      <div class="ba-field">
        <label class="ba-field-label" for="ba-scope">备份范围</label>
        <select id="ba-scope" v-model="scopeMode" class="ba-input">
          <option value="all">全部表（整库）</option>
          <option value="include">仅指定表</option>
          <option value="exclude">排除指定表</option>
        </select>
      </div>
      <div v-if="scopeMode !== 'all'" class="ba-field">
        <label class="ba-field-label" for="ba-tables">{{ scopeMode === 'include' ? '指定表（逗号或换行分隔）' : '排除表（逗号或换行分隔）' }}</label>
        <textarea id="ba-tables" v-model="tablesText" class="ba-input" rows="2" placeholder="例如：customers, orders, order_items" />
      </div>
      <p class="ba-adv-hint">表级备份走 JSON 路径，还原时按表 upsert，不会整库重建；表名以系统表清单为准。</p>
    </div>

    <div v-if="task?.taskId" class="ba-task">
      <div class="ba-task-head">
        <span class="ba-badge" :class="statusClass">{{ statusLabel }}</span>
        <span class="ba-task-title">{{ taskTitle }}</span>
      </div>
      <div class="ba-progress-row">
        <div class="ba-progress">
          <div class="ba-progress-fill" :class="task.status === 'failed' ? 'ba-fill-danger' : 'ba-fill-processing'" :style="{ width: pct + '%' }" />
        </div>
        <span class="ba-pct">{{ pct }}%</span>
      </div>
      <div class="ba-task-meta">
        <span class="ba-stage">{{ task.phaseLabel || task.phase }}</span>
        <span v-if="task.error" class="ba-error">{{ task.error }}</span>
      </div>
    </div>
    <div v-else-if="noTaskHint" class="ba-hint">{{ noTaskHint }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { showToast } from '@/composables/useToast'
import type { BackupTaskState, BackupTaskStatus } from './composables/useBackupTask'

/** 全量备份附加选项（P1-2 表级范围 + P2 加密密码输入） */
export interface FullBackupOptions {
  password?: string
  tables?: string[]
  excludeTables?: string[]
}

const props = defineProps<{
  busy: boolean
  task: BackupTaskState | null
  onFull: (opts?: FullBackupOptions) => void
  noTaskHint?: string
  /**
   * P1-20：后端 /backup/status 的加密状态。**必须用对象**而不是两个 boolean prop ——
   * Vue 的 Boolean 类型 prop 在「没传」时会强制成 false，正好把「状态没读到」
   * 误判成「加密已关闭」。null/undefined 表示状态未知。
   */
  encryption?: EncryptionState | null
}>()

const advancedOpen = ref(false)
const password = ref('')
const scopeMode = ref<'all' | 'include' | 'exclude'>('all')
const tablesText = ref('')

export interface EncryptionState {
  enabled: boolean
  passwordConfigured: boolean
}

/**
 * P1-20（2026-11-17 审计）：加密状态未知时按「可能加密」处理 —— 保留密码框，
 * 避免把「状态没读到」误当成「加密已关闭」而砍掉能力。只有后端明确说 enabled=false 才隐藏。
 */
const encryptionEnabled = computed(() => props.encryption?.enabled !== false)
/** 后端明确给了状态才渲染徽标；未知（未加载/老后端）不渲染，绝不谎称「已开启」 */
const encryptionKnown = computed(() => props.encryption != null)
const encryptionHint = computed(() => {
  const e = props.encryption
  if (!e) {
    return '加密状态未知（未加载或后端未上报）：留空则按服务端配置处理'
  }
  if (!e.enabled) {
    return '加密已关闭（BACKUP_ENCRYPTION_ENABLED=false）：本次备份为明文包，填写的密码会被后端忽略'
  }
  if (!e.passwordConfigured) {
    return '加密已开启但服务端未配置密码：填一个密码，或由运维补 BACKUP_ENCRYPTION_PASSWORD'
  }
  return '留空则用服务端配置的密码；两者都没有时后端会拒绝（绝不生成随机密钥）'
})

function parseTables(text: string): string[] {
  return text
    .split(/[,\n;]/)
    .map((s) => s.trim())
    .filter(Boolean)
}

function handleFull() {
  const tables = parseTables(tablesText.value)
  // P2（2026-10-24）：选了「仅指定表 / 排除指定表」但表名留空时，不能静默降级成整库备份
  // （运维以为在限定范围，实际按整库跑）。直接拦下并提示。
  if (scopeMode.value !== 'all' && tables.length === 0) {
    showToast(
      scopeMode.value === 'include' ? '请填写要备份的表名' : '请填写要排除的表名',
      'warning',
    )
    return
  }
  props.onFull({
    password: encryptionEnabled.value ? (password.value || undefined) : undefined,
    tables: scopeMode.value === 'include' && tables.length ? tables : undefined,
    excludeTables: scopeMode.value === 'exclude' && tables.length ? tables : undefined,
  })
}

const pct = computed(() => Math.round(props.task?.progress ?? 0))
const statusLabel = computed(() => {
  const s: BackupTaskStatus | '' = props.task?.status ?? ''
  if (s === 'completed' || s === 'completed_with_warnings') return '已完成'
  if (s === 'failed') return '失败'
  if (s === 'running' || s === 'pending') return '进行中'
  return ''
})
const statusClass = computed(() => {
  const s = props.task?.status
  if (s === 'failed') return 'ba-badge-danger'
  if (s === 'completed' || s === 'completed_with_warnings') return 'ba-badge-success'
  return 'ba-badge-processing'
})
const taskTitle = computed(() => {
  const s = props.task?.status
  if (s === 'completed' || s === 'completed_with_warnings') return '备份 · 已完成'
  if (s === 'failed') return '备份 · 失败'
  return '备份 · 执行中'
})
</script>

<style scoped>
.ba-card { border: 1px solid var(--color-border-light); border-radius: var(--radius-md, 14px); background: #ffffff; padding: 24px; box-shadow: 0 1px 3px rgba(0,0,0,.04), 0 4px 12px rgba(0,0,0,.06); }
.ba-actions { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.ba-btn { display: inline-flex; align-items: center; gap: 6px; padding: 9px 16px; border: 2px solid var(--color-border-light); border-radius: var(--radius-button, 14px); font-size: var(--fs-body-sm); font-weight: 600; font-family: inherit; line-height: 1.2; background: #ffffff; color: var(--color-text); cursor: pointer; transition: border-color .3s ease, color .3s ease, background .3s ease, box-shadow .3s ease, transform .3s ease; }
.ba-btn:disabled { opacity: .4; cursor: not-allowed; }
.ba-btn-primary { color: #fff; border-color: transparent; background: linear-gradient(135deg, var(--color-success-500), var(--color-success-600)); box-shadow: 0 4px 12px rgba(40, 199, 111, 0.24); }
.ba-btn-primary:hover:not(:disabled) { box-shadow: 0 6px 18px rgba(40, 199, 111, 0.32); transform: translateY(-1px); }
.ba-btn-outline { color: var(--color-primary-600); }
.ba-btn-outline:hover:not(:disabled) { background: var(--color-primary-50); border-color: var(--color-primary-300); color: var(--color-primary-700); box-shadow: 0 4px 12px rgba(0,0,0,.06); transform: translateY(-1px); }
.ba-mutex-hint { font-size: var(--fs-caption); color: var(--color-text-muted); }
.ba-enc-badge { font-size: var(--fs-caption); padding: 2px 8px; border-radius: 999px; font-weight: 600; }
.ba-enc-on { background: rgba(40, 199, 111, .12); color: var(--color-success-600); }
.ba-enc-off { background: rgba(255, 159, 67, .16); color: #b25e00; }
.ba-adv-warn { color: #b25e00; }
.ba-adv-toggle { border: none; background: none; cursor: pointer; font-size: var(--fs-caption); font-weight: 600; color: var(--color-primary-600); transition: color 0.2s ease; }
.ba-adv-toggle:hover { color: var(--color-primary-700); }
.ba-advanced { margin-top: 16px; padding: 16px; border: 1px dashed var(--color-border-light); border-radius: var(--radius-sm, 10px); display: flex; flex-direction: column; gap: 12px; }
.ba-field { display: flex; flex-direction: column; gap: 6px; }
.ba-field-label { font-size: var(--fs-caption); font-weight: 600; color: var(--color-text-secondary); }
.ba-input { height: 36px; padding: 0 12px; border: 1px solid var(--color-border-light); border-radius: var(--radius-input, 12px); font-size: var(--fs-body-sm); font-family: inherit; color: var(--color-text); background: #ffffff; }
.ba-input:focus { outline: none; border-color: var(--color-primary-300); box-shadow: 0 0 0 3px var(--color-primary-50); }
textarea.ba-input { height: auto; padding: 8px 12px; resize: vertical; font-family: var(--font-mono); }
.ba-adv-hint { margin: 0; font-size: var(--fs-caption); color: var(--color-text-muted); }
.ba-task { margin-top: 16px; border: 1px solid var(--color-border-light); border-radius: var(--radius-md, 14px); background: #ffffff; padding: 16px; }
.ba-task-head { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.ba-badge { min-width: 20px; height: 20px; padding: 0 8px; border-radius: 10px; font-size: var(--fs-caption); font-weight: 700; display: inline-flex; align-items: center; justify-content: center; white-space: nowrap; }
.ba-badge-processing { background: var(--color-primary-50); color: var(--color-primary-700); }
.ba-badge-success { background: var(--color-success-50); color: var(--color-success-700); }
.ba-badge-danger { background: var(--color-danger-50); color: var(--color-danger-700); }
.ba-task-title { font-size: var(--fs-body-sm); font-weight: 500; color: var(--color-text); }
.ba-progress-row { display: flex; align-items: center; gap: 12px; }
.ba-progress { flex: 1; height: 8px; background: var(--color-border-light); border-radius: 999px; overflow: hidden; }
.ba-progress-fill { height: 100%; border-radius: 999px; transition: width .2s ease; }
.ba-fill-processing { background: var(--color-primary-500, #5b8def); }
.ba-fill-danger { background: var(--color-danger-500, #ea5455); }
.ba-pct { min-width: 44px; text-align: right; font-variant-numeric: tabular-nums; font-size: var(--fs-body-sm); font-weight: 500; color: var(--color-text-secondary); }
.ba-task-meta { margin-top: 8px; display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.ba-stage { font-size: var(--fs-body-sm); color: var(--color-text-secondary); }
.ba-error { font-size: var(--fs-body-sm); color: var(--color-danger-500); }
.ba-hint { margin-top: 12px; font-size: var(--fs-body-sm); color: var(--color-text-muted); }
</style>