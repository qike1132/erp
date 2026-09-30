<template>
  <div v-if="open" class="rw-overlay" @click.self="onTryClose">
    <div class="rw-dialog">
      <div class="rw-head">
        <h3 class="rw-title">还原备份</h3>
        <button class="rw-icon-btn" :disabled="view === 'running'" @click="onTryClose">×</button>
      </div>

      <div class="rw-body">
        <!-- 确认态 -->
        <div v-if="view === 'form'">
          <p class="rw-desc">已选定要还原的备份点。还原将把该备份点数据覆盖到当前数据库，请确认影响范围后执行。</p>

          <select class="rw-select mono" :value="selected" @change="onSelectChange">
            <option v-for="f in options" :key="f.filename" :value="f.filename">{{ optionLabel(f) }}</option>
          </select>
          <div v-if="options.length === 0" class="rw-empty">暂无服务器备份可还原</div>

          <div v-if="planLoading" class="rw-loading">正在计算影响范围…</div>
          <template v-else-if="plan">
            <div class="rw-impact">
              <span>覆盖 <b>{{ plan.table_count ?? 0 }}</b> 张表 · <b>{{ plan.encrypted ? '加密包' : '明文包' }}</b></span>
              <span v-if="plan.affected_count" class="rw-affected">检测到 {{ plan.affected_count }} 张表有差异</span>
            </div>
            <div class="rw-table-wrap" v-if="plan.tables?.length">
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
            <div v-if="!plan.success" class="rw-error">{{ plan.error || '预览失败，无法执行还原' }}</div>
          </template>

          <p class="rw-desc rw-desc-danger">确认执行还原？此操作将覆盖当前数据库，且无法撤销。</p>
          <ul class="rw-danger-list">
            <li>将覆盖当前数据库全部数据</li>
            <li>执行期间系统停止写入</li>
            <li>未备份的新增数据将丢失</li>
          </ul>

          <div v-if="passwordRequired" class="rw-pw-row">
            <label class="rw-pw-label" for="rw-decrypt-pw">解密密码</label>
            <input
              id="rw-decrypt-pw"
              v-model="decryptPassword"
              class="rw-confirm-input"
              type="password"
              placeholder="该备份已加密，请输入解密密码"
              autocomplete="new-password"
              @blur="onPasswordBlur"
            />
          </div>

          <label class="rw-sensitive-check">
            <input v-model="confirmSensitive" type="checkbox" />
            <span>同时还原敏感配置文件（.env.production / jwt 密钥）——默认跳过，仅确有需要时勾选</span>
          </label>

          <input v-model="confirmText" class="rw-confirm-input" placeholder="输入「确认还原」以继续" autocomplete="off" />
        </div>

        <!-- 进度态 -->
        <div v-else-if="view === 'running'">
          <p class="rw-desc">正在执行还原，此过程不可中断。</p>
          <div class="rw-progress-row">
            <div class="rw-progress">
              <div
                class="rw-progress-fill"
                :class="task?.status === 'failed' ? 'rw-fill-danger' : 'rw-fill-processing'"
                :style="{ width: pct + '%' }"
              ></div>
            </div>
            <span class="rw-pct mono">{{ pct }}%</span>
          </div>
          <div class="rw-stage">
            {{ task?.status === 'failed' ? (task?.error || '还原失败') : (task?.phaseLabel || '准备还原环境…') }}
          </div>
        </div>

        <!-- 结果态 -->
        <div v-else class="rw-report">
          <div class="rw-report-icon" :class="{ 'rw-report-icon-danger': isFailed }">{{ isFailed ? '✕' : '✓' }}</div>
          <div class="rw-report-title">{{ resultTitle }}</div>
          <p class="rw-report-sub">{{ result?.error || '还原流程已结束，请核对校验结果' }}</p>
        </div>
      </div>

      <div class="rw-foot">
        <button v-if="view !== 'done'" class="rw-btn" :disabled="view === 'running'" @click="onTryClose">取消</button>
        <span v-else></span>
        <div class="rw-foot-right">
          <button v-if="view === 'form'" class="rw-btn rw-btn-danger" :disabled="!canExecute" @click="doExecute">确认还原</button>
          <button v-if="view === 'done'" class="rw-btn rw-btn-primary" @click="onTryClose">完成</button>
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

/** 还原执行选项（敏感配置确认 + 加密包解密密码） */
export interface RestoreExecuteOptions {
  confirmSensitive: boolean
  password?: string
}

const CONFIRM_TEXT = '确认还原'

const props = defineProps<{
  open: boolean
  serverBackups: ServerBackupSummary[]
  initialFilename: string
  plan: BackupRestorePlan | null
  planLoading: boolean
  task: BackupTaskState | null
  result: BackupTaskState | null
  onPlan: (filename: string, password?: string) => void
  onExecute: (filename: string, opts: RestoreExecuteOptions) => Promise<boolean>
}>()

const emit = defineEmits<{ close: [] }>()

const view = ref<'form' | 'running' | 'done'>('form')
const selected = ref('')
/** 记录行触发的备份点：即使不在服务器清单中也始终置顶，切走其他备份点后仍可切回 */
const pinnedFilename = ref('')
const confirmText = ref('')
const confirmSensitive = ref(false)
const decryptPassword = ref('')

/** 下拉选项；置顶项保证记录行触发的备份点一定可选 */
const options = computed<ServerBackupSummary[]>(() => {
  if (pinnedFilename.value && !props.serverBackups.some((b) => b.filename === pinnedFilename.value)) {
    return [{ filename: pinnedFilename.value }, ...props.serverBackups]
  }
  return props.serverBackups
})

/** 需要解密密码：以预览结果为准，并以文件名兜底 —— 预览失败时 `plan.encrypted`
 *  可能拿不到，而加密包没有密码根本无法还原，输入框绝不能因此不出现。 */
const passwordRequired = computed(() => !!props.plan?.encrypted || /\.enc$/i.test(selected.value))

const canExecute = computed(() =>
  confirmText.value === CONFIRM_TEXT &&
  !!selected.value &&
  !props.planLoading &&
  // 加密包：密码给了就放行 —— 无密码时预览必然失败，若死等 plan.success 则永远点不动
  (!!props.plan?.success || (passwordRequired.value && !!decryptPassword.value)) &&
  (!passwordRequired.value || !!decryptPassword.value),
)

const pct = computed(() => Math.round(props.task?.progress ?? 0))
const isFailed = computed(() => props.result?.status === 'failed')
const resultTitle = computed(() => {
  const s = props.result?.status
  if (s === 'failed') return '还原失败'
  if (s === 'completed_with_warnings') return '还原完成（有警告）'
  return '还原完成'
})

watch(() => props.open, (o) => {
  if (!o) return
  pinnedFilename.value = props.initialFilename
  selected.value = props.initialFilename || props.serverBackups[0]?.filename || ''
  confirmText.value = ''
  confirmSensitive.value = false
  decryptPassword.value = ''
  view.value = 'form'
  if (selected.value) props.onPlan(selected.value)
})

// 服务器备份清单晚于弹窗打开才返回时，补选首项并拉取预览
watch(() => props.serverBackups, (list) => {
  if (!props.open || selected.value) return
  const first = list[0]
  if (!first) return
  selected.value = first.filename
  props.onPlan(first.filename)
})

// 终态由父级下传的快照驱动：统一轮询在终态会复位任务状态，不能依赖 task
watch(() => props.result, (r) => {
  if (r) view.value = 'done'
})

function onSelectChange(e: Event) {
  const value = (e.target as HTMLSelectElement).value
  if (!value || value === selected.value) return
  selected.value = value
  confirmText.value = ''
  decryptPassword.value = ''
  props.onPlan(value)
}

/** 密码填完后重跑一次预览：拿到真实差异表，而不是一直显示「预览失败」 */
function onPasswordBlur() {
  if (!passwordRequired.value || !selected.value) return
  if (props.plan?.success) return
  const pw = decryptPassword.value
  if (pw) props.onPlan(selected.value, pw)
}

async function doExecute() {
  if (!canExecute.value) return
  view.value = 'running'
  // 入队失败（如后端 409 已有任务在跑）必须回退表单态，否则弹窗永久卡在进度态且无法关闭
  const ok = await props.onExecute(selected.value, {
    confirmSensitive: confirmSensitive.value,
    password: decryptPassword.value || undefined,
  })
  if (!ok) view.value = 'form'
}

function onTryClose() {
  if (view.value === 'running') return
  emit('close')
}

function optionLabel(f: ServerBackupSummary) {
  const parts = [f.filename]
  if (f.size != null) parts.push(fmtSize(f.size))
  if (f.created_at) parts.push(f.created_at.slice(0, 16))
  return parts.join(' · ')
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
.rw-body { padding: 16px 28px 28px; overflow-y: auto; }
.rw-desc { font-size: 14px; color: var(--color-text-secondary); margin-bottom: 16px; }
.rw-desc-danger { color: var(--color-danger-500); margin-top: 20px; margin-bottom: 12px; }
.rw-select { width: 100%; height: 36px; padding: 0 12px; border: 1px solid var(--color-border-light); border-radius: var(--radius-input, 12px); font-size: 13px; font-family: inherit; color: var(--color-text); background: #ffffff; margin-bottom: 16px; transition: border-color 0.2s ease, box-shadow 0.2s ease; }
.rw-select:focus { outline: none; border-color: var(--color-primary-300); box-shadow: 0 0 0 3px var(--color-primary-50); }
.rw-loading { font-size: 13px; color: var(--color-text-muted); margin-bottom: 16px; }
.rw-empty { font-size: 13px; color: var(--color-text-muted); margin-bottom: 16px; }
.rw-impact { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 16px; font-size: 14px; color: var(--color-text); }
.rw-impact b { color: var(--color-primary-700); }
.rw-affected { color: var(--color-warning-700); }
.rw-table-wrap { overflow-x: auto; border: 1px solid var(--color-border-light); border-radius: var(--radius-sm, 10px); margin-bottom: 16px; }
.rw-table { width: 100%; border-collapse: collapse; min-width: 480px; }
.rw-table th { text-align: left; font-size: 12px; font-weight: 600; color: var(--color-text-secondary); padding: 12px; background: var(--color-surface); border-bottom: 1px solid var(--color-border-light); }
.rw-table td { padding: 0 12px; height: 40px; font-size: 13px; color: var(--color-text); border-bottom: 1px solid var(--color-border-light); }
.rw-table tbody tr:last-child td { border-bottom: none; }
.rw-error { margin-bottom: 16px; color: var(--color-danger-500); font-size: 13px; }
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
.rw-report-icon-danger { background: var(--color-danger-50); color: var(--color-danger-500); }
.rw-report-title { font-size: 18px; font-weight: 700; color: var(--color-text); }
.rw-report-sub { margin-top: 6px; font-size: 14px; color: var(--color-text-secondary); }
.rw-foot { display: flex; align-items: center; justify-content: space-between; padding: 16px 28px; border-top: 1px solid var(--color-border-light); }
.rw-foot-right { display: flex; gap: 12px; }
.rw-btn { display: inline-flex; align-items: center; height: 36px; padding: 0 16px; border-radius: var(--radius-button, 14px); font-size: 13px; font-weight: 600; font-family: inherit; cursor: pointer; border: 2px solid var(--color-border-light); background: #ffffff; color: var(--color-text-secondary); transition: background 0.2s ease, border-color 0.2s ease, color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease; }
.rw-btn:hover:not(:disabled) { border-color: var(--color-primary-300); color: var(--color-primary-700); }
.rw-btn:disabled { opacity: .5; cursor: not-allowed; }
.rw-btn-danger { background: linear-gradient(135deg, var(--color-danger-500), var(--color-danger-600)); color: #fff; border-color: transparent; box-shadow: 0 4px 12px rgba(234, 84, 85, 0.24); }
.rw-btn-danger:hover:not(:disabled) { color: #fff; box-shadow: 0 6px 18px rgba(234, 84, 85, 0.32); transform: translateY(-1px); }
.rw-btn-primary { background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700)); color: #fff; border-color: transparent; box-shadow: 0 4px 12px rgba(91, 141, 239, 0.24); }
.rw-btn-primary:hover:not(:disabled) { color: #fff; box-shadow: 0 6px 18px rgba(91, 141, 239, 0.32); transform: translateY(-1px); }
.mono { font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace; }

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
@keyframes slideUp {
  from { opacity: 0; transform: translateY(20px) scale(0.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
</style>
