<template>
  <div v-if="open" class="rw-overlay" @click.self="onTryClose">
    <div class="rw-dialog">
      <div class="rw-head">
        <h3 class="rw-title">还原向导</h3>
        <button class="rw-icon-btn" :disabled="step === 4" @click="onTryClose">×</button>
      </div>

      <div class="rw-stepper">
        <template v-for="(s, i) in steps" :key="s">
          <div class="rw-step" :class="stepCls(i + 1)">
            <span class="rw-step-dot">{{ stepDone(i + 1) ? '✓' : i + 1 }}</span>
            <span class="rw-step-label">{{ s }}</span>
          </div>
          <div v-if="i < steps.length - 1" class="rw-step-line" :class="{ done: step > i + 1 }"></div>
        </template>
      </div>

      <div class="rw-body">
        <!-- Step 1 选择备份点 -->
        <div v-show="step === 1">
          <p class="rw-desc">选择一个备份点用于还原。还原将把该备份点数据覆盖到当前数据库。</p>
          <label v-for="f in serverBackups" :key="f.filename" class="rw-point" :class="{ checked: selected === f.filename }">
            <input type="radio" :checked="selected === f.filename" @change="selectPoint(f.filename)" />
            <span class="mono rw-point-name">{{ f.filename }}</span>
            <span class="mono rw-point-meta">{{ fmtSize(f.size) }} · {{ f.created_at?.slice(0, 16) }}</span>
          </label>
          <div v-if="serverBackups.length === 0" class="rw-empty">暂无服务器备份可还原</div>
        </div>

        <!-- Step 2 差异预览 -->
        <div v-show="step === 2">
          <p class="rw-desc">还原将覆盖以下数据，请确认影响范围。</p>
          <div class="rw-impact" v-if="plan">
            <span>覆盖 <b>{{ plan.table_count }}</b> 张表 · <b>{{ plan.encrypted ? '加密包' : '明文包' }}</b></span>
            <span v-if="plan.affected_count" class="rw-affected">检测到 {{ plan.affected_count }} 张表有差异</span>
          </div>
          <div class="rw-table-wrap" v-if="plan?.tables?.length">
            <table class="rw-table">
              <thead><tr><th>表名</th><th>备份行数</th><th>当前行数</th><th>差异</th></tr></thead>
              <tbody>
                <tr v-for="t in plan.tables" :key="t.table">
                  <td class="mono">{{ t.table }}</td>
                  <td class="mono">{{ t.backup_rows ?? '—' }}</td>
                  <td class="mono">{{ t.current_rows ?? '—' }}</td>
                  <td class="mono">{{ t.diff == null ? '—' : t.diff === 0 ? '一致' : (t.diff > 0 ? '+' + t.diff : String(t.diff)) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-if="plan && !plan.success" class="rw-error">{{ plan.error }}</div>
        </div>

        <!-- Step 3 危险确认 -->
        <div v-show="step === 3">
          <p class="rw-desc">确认执行还原？此操作将覆盖当前数据库，且无法撤销。</p>
          <ul class="rw-danger-list">
            <li>将覆盖当前数据库全部数据</li>
            <li>执行期间系统停止写入</li>
            <li>未备份的新增数据将丢失</li>
          </ul>
          <div v-if="plan?.encrypted" class="rw-pw-row">
            <label class="rw-pw-label" for="rw-decrypt-pw">解密密码</label>
            <input
              id="rw-decrypt-pw"
              v-model="decryptPassword"
              class="rw-confirm-input"
              type="password"
              placeholder="该备份已加密，请输入解密密码"
              autocomplete="new-password"
            />
          </div>
          <label class="rw-sensitive-check">
            <input v-model="confirmSensitive" type="checkbox" />
            <span>同时还原敏感配置文件（.env.production / jwt 密钥）——默认跳过，仅确有需要时勾选</span>
          </label>
          <input v-model="confirmText" class="rw-confirm-input" placeholder="输入「确认还原」以继续" autocomplete="off" />
        </div>

        <!-- Step 4 执行进度 -->
        <div v-show="step === 4">
          <p class="rw-desc">正在执行还原，此过程不可中断。</p>
          <div class="rw-progress-row">
            <div class="rw-progress">
              <div class="rw-progress-fill" :class="task?.status === 'failed' ? 'rw-fill-danger' : 'rw-fill-processing'" :style="{ width: pct + '%' }"></div>
            </div>
            <span class="rw-pct mono">{{ pct }}%</span>
          </div>
          <div class="rw-stage">{{ (task?.status ?? '') === 'failed' ? (task?.error || '还原失败') : (task?.phaseLabel || '准备还原环境…') }}</div>
        </div>

        <!-- Step 5 结果报告 -->
        <div v-show="step === 5" class="rw-report">
          <div class="rw-report-icon">✓</div>
          <div class="rw-report-title">还原{{ (task?.status ?? '') === 'completed_with_warnings' ? '完成（有警告）' : (task?.status ?? '') === 'failed' ? '失败' : '完成' }}</div>
          <p class="rw-report-sub">{{ task?.error || '还原流程已结束，请核对校验结果' }}</p>
        </div>
      </div>

      <div class="rw-foot">
        <button class="rw-btn" :disabled="step <= 1 || step === 4" @click="prev">上一步</button>
        <div class="rw-foot-right">
          <button v-if="step < 3 && step !== 4" class="rw-btn rw-btn-primary" :disabled="canNextDisabled" @click="next">下一步</button>
          <button v-if="step === 3" class="rw-btn rw-btn-danger" :disabled="confirmText !== '确认还原'" @click="doExecute">确认还原</button>
          <button v-if="step === 5" class="rw-btn rw-btn-primary" @click="close">完成</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { BackupRestorePlan } from '@/api/backup'
import type { BackupTaskState } from './composables/useBackupTask'

export interface ServerBackupSummary {
  filename: string
  size?: number
  created_at?: string | null
}

/** 还原执行选项（P0-2：敏感配置确认 + 加密包解密密码） */
export interface RestoreExecuteOptions {
  confirmSensitive: boolean
  password?: string
}

const props = defineProps<{
  open: boolean
  serverBackups: ServerBackupSummary[]
  plan: BackupRestorePlan | null
  task: BackupTaskState | null
  onPreview: (filename: string) => void
  onExecute: (filename: string, opts: RestoreExecuteOptions) => void
}>()

const emit = defineEmits<{ close: [] }>()

const steps = ['选择备份点', '差异预览', '还原确认', '执行还原', '结果报告']
const step = ref(1)
const selected = ref('')
const confirmText = ref('')
const confirmSensitive = ref(false)
const decryptPassword = ref('')

watch(() => props.open, (o) => {
  if (o) {
    step.value = 1
    confirmText.value = ''
    confirmSensitive.value = false
    decryptPassword.value = ''
  }
})

watch(() => props.task, (t) => {
  if (!t) return
  if (t.status === 'completed' || t.status === 'completed_with_warnings' || t.status === 'failed') {
    step.value = 5
  }
})

const pct = computed(() => Math.round(props.task?.progress ?? 0))
const canNextDisabled = computed(() => (step.value === 1 && !selected.value) || (step.value === 2 && (!props.plan || !props.plan.success)))

function stepCls(n: number) {
  if (step.value > n) return 'done'
  if (step.value === n) return 'current'
  return ''
}
function stepDone(n: number) {
  return step.value > n
}
function selectPoint(f: string) {
  selected.value = f
}
function next() {
  if (step.value === 1 && selected.value) {
    step.value = 2
    props.onPreview(selected.value)
  } else if (step.value === 2) {
    step.value = 3
  }
}
function prev() {
  step.value = Math.max(1, step.value - 1)
}
function doExecute() {
  if (confirmText.value === '确认还原' && selected.value) {
    step.value = 4
    props.onExecute(selected.value, {
      confirmSensitive: confirmSensitive.value,
      password: decryptPassword.value || undefined,
    })
  }
}
function close() {
  emit('close')
}
function onTryClose() {
  if (step.value !== 4) close()
}
function fmtSize(n?: number) {
  if (n == null) return '—'
  const gb = n / 1024 / 1024 / 1024
  const mb = n / 1024 / 1024
  if (gb >= 1) return `${gb.toFixed(1)} GB`
  if (mb >= 1) return `${Math.round(mb)} MB`
  return `${Math.round(n / 1024)} KB`
}
</script>

<style scoped>
.rw-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.32); backdrop-filter: blur(2px); z-index: var(--z-modal, 40); display: flex; align-items: center; justify-content: center; padding: 16px; animation: fadeIn 0.2s ease; }
.rw-dialog { width: 100%; max-width: 720px; max-height: calc(100vh - 32px); background: var(--color-surface-card, #ffffff); border-radius: var(--radius-modal, 28px); box-shadow: var(--shadow-lg, 0 8px 32px rgba(135, 206, 235, 0.28)); display: flex; flex-direction: column; overflow: hidden; animation: slideUp 0.3s ease; }
.rw-head { display: flex; align-items: center; justify-content: space-between; padding: 24px 28px 0; }
.rw-title { font-size: 18px; font-weight: 700; color: var(--color-text); margin: 0; letter-spacing: -0.01em; }
.rw-icon-btn { width: 32px; height: 32px; border: 1px solid var(--color-border-light); border-radius: 50%; background: #ffffff; color: var(--color-text-secondary); cursor: pointer; font-size: 18px; line-height: 1; display: inline-flex; align-items: center; justify-content: center; transition: background 0.2s ease, color 0.2s ease; }
.rw-icon-btn:hover:not(:disabled) { background: var(--color-danger-50); color: var(--color-danger-500); }
.rw-icon-btn:disabled { opacity: .5; cursor: not-allowed; }
.rw-stepper { display: flex; align-items: center; padding: 24px 28px 8px; overflow-x: auto; }
.rw-step { display: flex; align-items: center; flex: none; }
.rw-step-dot { width: 26px; height: 26px; border-radius: 50%; border: 2px solid var(--color-border); color: var(--color-text-muted); display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 600; }
.rw-step.done .rw-step-dot { background: var(--color-success-500); border-color: var(--color-success-500); color: #fff; }
.rw-step.current .rw-step-dot { background: var(--color-primary-500); border-color: var(--color-primary-500); color: #fff; box-shadow: 0 0 0 4px var(--color-primary-50); }
.rw-step-label { margin-left: 8px; font-size: 14px; white-space: nowrap; color: var(--color-text-secondary); }
.rw-step.current .rw-step-label { color: var(--color-primary-600); font-weight: 600; }
.rw-step.done .rw-step-label { color: var(--color-text); }
.rw-step-line { width: 32px; height: 2px; background: var(--color-border); margin: 0 8px; flex: none; }
.rw-step-line.done { background: var(--color-success-500); }
.rw-body { padding: 12px 28px 28px; overflow-y: auto; }
.rw-desc { font-size: 14px; color: var(--color-text-secondary); margin-bottom: 16px; }
.rw-point { display: flex; align-items: center; gap: 12px; border: 1px solid var(--color-border-light); border-radius: var(--radius-sm, 10px); padding: 14px 16px; margin-bottom: 8px; cursor: pointer; background: #ffffff; transition: border-color 0.2s ease, background 0.2s ease, box-shadow 0.2s ease; }
.rw-point:hover { border-color: var(--color-primary-300); }
.rw-point.checked { border-color: var(--color-primary-400); background: var(--color-primary-50); box-shadow: 0 0 0 3px var(--color-primary-50); }
.rw-point input { accent-color: var(--color-primary-600); }
.rw-point-name { flex: 1; font-size: 13px; color: var(--color-text); }
.rw-point-meta { font-size: 12px; color: var(--color-text-muted); }
.mono { font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace; }
.rw-empty { color: var(--color-text-muted); font-size: 13px; }
.rw-impact { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 16px; font-size: 14px; color: var(--color-text); }
.rw-impact b { color: var(--color-primary-700); }
.rw-affected { color: var(--color-warning-700); }
.rw-table-wrap { overflow-x: auto; border: 1px solid var(--color-border-light); border-radius: var(--radius-sm, 10px); }
.rw-table { width: 100%; border-collapse: collapse; min-width: 480px; }
.rw-table th { text-align: left; font-size: 12px; font-weight: 600; color: var(--color-text-secondary); padding: 12px; background: var(--color-surface); border-bottom: 1px solid var(--color-border-light); }
.rw-table td { padding: 0 12px; height: 40px; font-size: 13px; color: var(--color-text); border-bottom: 1px solid var(--color-border-light); }
.rw-table tbody tr:last-child td { border-bottom: none; }
.rw-error { margin-top: 12px; color: var(--color-danger-500); font-size: 13px; }
.rw-danger-list { list-style: none; margin: 0 0 16px; padding: 0; }
.rw-danger-list li { display: flex; align-items: center; gap: 8px; font-size: 14px; color: var(--color-danger-500); margin-bottom: 8px; }
.rw-danger-list li::before { content: ''; width: 6px; height: 6px; border-radius: 50%; background: var(--color-danger-500); }
.rw-confirm-input { width: 100%; height: 36px; padding: 0 12px; border: 1px solid var(--color-border-light); border-radius: var(--radius-input, 12px); font-size: 14px; font-family: inherit; color: var(--color-text); background: #ffffff; transition: border-color 0.2s ease, box-shadow 0.2s ease; }
.rw-confirm-input:focus { outline: none; border-color: var(--color-primary-300); box-shadow: 0 0 0 3px var(--color-primary-50); }
.rw-pw-row { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.rw-pw-label { font-size: 13px; color: var(--color-text-secondary); white-space: nowrap; }
.rw-pw-row .rw-confirm-input { flex: 1; }
.rw-sensitive-check { display: flex; align-items: flex-start; gap: 8px; margin: 4px 0 16px; font-size: 13px; color: var(--color-text-secondary); cursor: pointer; }
.rw-sensitive-check input { accent-color: var(--color-primary-600); margin-top: 2px; }
.rw-progress-row { display: flex; align-items: center; gap: 12px; margin: 16px 0; }
.rw-progress { flex: 1; height: 8px; background: var(--color-border-light); border-radius: 999px; overflow: hidden; }
.rw-progress-fill { height: 100%; border-radius: 999px; transition: width .2s ease; }
.rw-fill-processing { background: var(--color-danger-500, #ea5455); }
.rw-fill-danger { background: var(--color-danger-600, #d44042); }
.rw-pct { min-width: 44px; text-align: right; font-variant-numeric: tabular-nums; font-size: 14px; font-weight: 600; color: var(--color-text-secondary); }
.rw-stage { font-size: 13px; color: var(--color-text-secondary); }
.rw-report { text-align: center; padding: 24px 0 8px; }
.rw-report-icon { width: 52px; height: 52px; border-radius: 50%; background: var(--color-success-50); color: var(--color-success-500); display: inline-flex; align-items: center; justify-content: center; font-size: 26px; margin-bottom: 12px; }
.rw-report-title { font-size: 18px; font-weight: 700; color: var(--color-text); }
.rw-report-sub { margin-top: 6px; font-size: 14px; color: var(--color-text-secondary); }
.rw-foot { display: flex; align-items: center; justify-content: space-between; padding: 16px 28px; border-top: 1px solid var(--color-border-light); }
.rw-foot-right { display: flex; gap: 12px; }
.rw-btn { display: inline-flex; align-items: center; height: 36px; padding: 0 16px; border-radius: var(--radius-button, 14px); font-size: 13px; font-weight: 600; font-family: inherit; cursor: pointer; border: 2px solid var(--color-border-light); background: #ffffff; color: var(--color-text-secondary); transition: background 0.2s ease, border-color 0.2s ease, color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease; }
.rw-btn:hover:not(:disabled) { border-color: var(--color-primary-300); color: var(--color-primary-700); }
.rw-btn:disabled { opacity: .5; cursor: not-allowed; }
.rw-btn-primary { background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700)); color: #fff; border-color: transparent; box-shadow: 0 4px 12px rgba(91, 141, 239, 0.24); }
.rw-btn-primary:hover:not(:disabled) { color: #fff; box-shadow: 0 6px 18px rgba(91, 141, 239, 0.32); transform: translateY(-1px); }
.rw-btn-danger { background: linear-gradient(135deg, var(--color-danger-500), var(--color-danger-600)); color: #fff; border-color: transparent; box-shadow: 0 4px 12px rgba(234, 84, 85, 0.24); }
.rw-btn-danger:hover:not(:disabled) { color: #fff; box-shadow: 0 6px 18px rgba(234, 84, 85, 0.32); transform: translateY(-1px); }

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
@keyframes slideUp {
  from { opacity: 0; transform: translateY(20px) scale(0.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
</style>