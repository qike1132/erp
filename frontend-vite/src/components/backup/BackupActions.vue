<template>
  <div class="ba-card">
    <div class="ba-actions">
      <button class="ba-btn ba-btn-primary" :disabled="busy || !!task?.taskId" @click="handleFull">
        一键全量备份
      </button>
      <button class="ba-btn ba-btn-outline" :disabled="busy || !!task?.taskId" @click="onIncremental">
        增量备份
      </button>
      <button class="ba-adv-toggle" @click="advancedOpen = !advancedOpen">
        {{ advancedOpen ? '收起选项' : '高级选项' }}
      </button>
      <span v-if="busy" class="ba-mutex-hint">有任务执行中</span>
    </div>

    <div v-if="advancedOpen" class="ba-advanced">
      <div class="ba-field">
        <label class="ba-field-label" for="ba-enc-pw">加密密码（可选）</label>
        <input id="ba-enc-pw" v-model="password" type="password" class="ba-input" autocomplete="new-password"
               placeholder="留空则按服务端配置：环境变量密码或明文（绝不随机密钥）"
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
  onIncremental: () => void
  noTaskHint?: string
}>()

const advancedOpen = ref(false)
const password = ref('')
const scopeMode = ref<'all' | 'include' | 'exclude'>('all')
const tablesText = ref('')

function parseTables(text: string): string[] {
  return text
    .split(/[,\n;]/)
    .map((s) => s.trim())
    .filter(Boolean)
}

function handleFull() {
  const tables = parseTables(tablesText.value)
  props.onFull({
    password: password.value || undefined,
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
.ba-btn { display: inline-flex; align-items: center; gap: 6px; padding: 9px 16px; border: 2px solid var(--color-border-light); border-radius: var(--radius-button, 14px); font-size: 13px; font-weight: 600; font-family: inherit; line-height: 1.2; background: #ffffff; color: var(--color-text); cursor: pointer; transition: border-color .3s ease, color .3s ease, background .3s ease, box-shadow .3s ease, transform .3s ease; }
.ba-btn:disabled { opacity: .4; cursor: not-allowed; }
.ba-btn-primary { color: #fff; border-color: transparent; background: linear-gradient(135deg, var(--color-success-500), var(--color-success-600)); box-shadow: 0 4px 12px rgba(40, 199, 111, 0.24); }
.ba-btn-primary:hover:not(:disabled) { box-shadow: 0 6px 18px rgba(40, 199, 111, 0.32); transform: translateY(-1px); }
.ba-btn-outline { color: var(--color-primary-600); }
.ba-btn-outline:hover:not(:disabled) { background: var(--color-primary-50); border-color: var(--color-primary-300); color: var(--color-primary-700); box-shadow: 0 4px 12px rgba(0,0,0,.06); transform: translateY(-1px); }
.ba-mutex-hint { font-size: 12px; color: var(--color-text-muted); }
.ba-adv-toggle { border: none; background: none; cursor: pointer; font-size: 12px; font-weight: 600; color: var(--color-primary-600); transition: color 0.2s ease; }
.ba-adv-toggle:hover { color: var(--color-primary-700); }
.ba-advanced { margin-top: 16px; padding: 16px; border: 1px dashed var(--color-border-light); border-radius: var(--radius-sm, 10px); display: flex; flex-direction: column; gap: 12px; }
.ba-field { display: flex; flex-direction: column; gap: 6px; }
.ba-field-label { font-size: 12px; font-weight: 600; color: var(--color-text-secondary); }
.ba-input { height: 36px; padding: 0 12px; border: 1px solid var(--color-border-light); border-radius: var(--radius-input, 12px); font-size: 13px; font-family: inherit; color: var(--color-text); background: #ffffff; }
.ba-input:focus { outline: none; border-color: var(--color-primary-300); box-shadow: 0 0 0 3px var(--color-primary-50); }
textarea.ba-input { height: auto; padding: 8px 12px; resize: vertical; font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace; }
.ba-adv-hint { margin: 0; font-size: 12px; color: var(--color-text-muted); }
.ba-task { margin-top: 16px; border: 1px solid var(--color-border-light); border-radius: var(--radius-md, 14px); background: #ffffff; padding: 16px; }
.ba-task-head { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.ba-badge { min-width: 20px; height: 20px; padding: 0 8px; border-radius: 10px; font-size: 11px; font-weight: 700; display: inline-flex; align-items: center; justify-content: center; white-space: nowrap; }
.ba-badge-processing { background: var(--color-primary-50); color: var(--color-primary-700); }
.ba-badge-success { background: var(--color-success-50); color: var(--color-success-700); }
.ba-badge-danger { background: var(--color-danger-50); color: var(--color-danger-700); }
.ba-task-title { font-size: 14px; font-weight: 500; color: var(--color-text); }
.ba-progress-row { display: flex; align-items: center; gap: 12px; }
.ba-progress { flex: 1; height: 8px; background: var(--color-border-light); border-radius: 999px; overflow: hidden; }
.ba-progress-fill { height: 100%; border-radius: 999px; transition: width .2s ease; }
.ba-fill-processing { background: var(--color-primary-500, #5b8def); }
.ba-fill-danger { background: var(--color-danger-500, #ea5455); }
.ba-pct { min-width: 44px; text-align: right; font-variant-numeric: tabular-nums; font-size: 14px; font-weight: 500; color: var(--color-text-secondary); }
.ba-task-meta { margin-top: 8px; display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.ba-stage { font-size: 13px; color: var(--color-text-secondary); }
.ba-error { font-size: 13px; color: var(--color-danger-500); }
.ba-hint { margin-top: 12px; font-size: 13px; color: var(--color-text-muted); }
</style>