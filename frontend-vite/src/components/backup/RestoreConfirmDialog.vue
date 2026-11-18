<template>
  <!-- 还原确认框（2026-10-17 审计 P1-19）：改走共享 `UiDialog`。
       原先手搓 `<div class="rw-overlay">` 当模态：没有焦点陷阱、没有 role="dialog"/aria-modal、
       没有 Esc 处理、没有 body 滚动锁。后果是打开后按 Tab 焦点仍停在被点的「还原」按钮上，
       继续 Tab 就到同行的「下载」/「删除」甚至「一键全量备份」——焦点在背景按钮上按回车
       照常派发 click，等于在一个待确认的全库覆盖之上又删了一个备份文件；读屏器也完全
       不知道有模态弹窗打开。
       全站约定（2026-10-14）：点遮罩空白不关闭弹窗，只走 ✕ / 取消 / Esc。 -->
  <UiDialog
    :open="open"
    sr-title="还原备份"
    description="确认还原影响范围；执行后会覆盖当前数据库且无法撤销"
    max-width-class="max-w-[720px]"
    :body-padded="false"
    :close-on-overlay-click="false"
    @update:open="onDialogOpenChange"
  >
    <div class="rw-head">
      <h3 class="rw-title">还原备份</h3>
      <!-- 执行中（running）禁止关闭：还原不可中断，onTryClose 也会再挡一次 -->
      <button
        class="rw-icon-btn"
        :disabled="view === 'running'"
        aria-label="关闭"
        @click="onTryClose"
      >×</button>
    </div>

    <div class="rw-body">
      <!-- 确认态 -->
      <div v-if="view === 'form'">
        <p class="rw-desc">已选定要还原的备份点。还原将把该备份点数据覆盖到当前数据库，请确认影响范围后执行。</p>

        <!-- 还原目标由记录行「还原」按钮唯一指定，不再提供弹窗内切换 -->
        <div class="rw-file mono" :title="selected">{{ selected || '未指定备份文件' }}</div>

        <div v-if="planLoading" class="rw-loading">正在计算影响范围…</div>
        <template v-else-if="plan">
          <div class="rw-impact">
            <span>覆盖 <b>{{ plan.table_count ?? 0 }}</b> 张表 · <b>{{ plan.encrypted ? '加密包' : '明文包' }}</b></span>
          </div>
          <div v-if="!plan.success" class="rw-error">{{ plan.error || '预览失败，无法执行还原' }}</div>
        </template>

        <p class="rw-desc rw-desc-danger">确认执行还原？此操作将覆盖当前数据库，且无法撤销。</p>
        <ul class="rw-danger-list">
          <li>将覆盖当前数据库全部数据</li>
          <li>执行期间系统停止写入</li>
          <li>未备份的新增数据将丢失</li>
        </ul>

        <label class="rw-sensitive-check">
          <input v-model="confirmSensitive" type="checkbox" />
          <span>同时还原敏感配置文件（.env.production / jwt 密钥）——默认跳过，仅确有需要时勾选</span>
        </label>

        <label class="rw-overwrite-check">
          <input v-model="confirmOverwrite" type="checkbox" />
          <span>我已知晓：还原将覆盖当前数据库全部数据且无法撤销</span>
        </label>
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
            />
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

    <template #footer>
      <button v-if="view !== 'done'" class="rw-btn" :disabled="view === 'running'" @click="onTryClose">取消</button>
      <button v-if="view === 'form'" class="rw-btn rw-btn-danger" :disabled="!canExecute" @click="doExecute">确认还原</button>
      <button v-if="view === 'done'" class="rw-btn rw-btn-primary" @click="onTryClose">完成</button>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import type { BackupRestorePlan } from '@/api/backup'
import type { BackupTaskState } from './composables/useBackupTask'

/** 还原执行选项（敏感配置确认）。解密密码不再由用户输入：
 *  备份由服务端用 BACKUP_ENCRYPTION_PASSWORD 加密，还原时后端经
 *  _get_encryption_password 自动回退到同一环境变量解密。 */
export interface RestoreExecuteOptions {
  confirmSensitive: boolean
}

const props = defineProps<{
  open: boolean
  initialFilename: string
  plan: BackupRestorePlan | null
  planLoading: boolean
  task: BackupTaskState | null
  result: BackupTaskState | null
  onPlan: (filename: string) => void
  onExecute: (filename: string, opts: RestoreExecuteOptions) => Promise<boolean>
}>()

const emit = defineEmits<{ close: [] }>()

const view = ref<'form' | 'running' | 'done'>('form')
const selected = ref('')
const confirmOverwrite = ref(false)
const confirmSensitive = ref(false)

const canExecute = computed(() =>
  confirmOverwrite.value &&
  !!selected.value &&
  !props.planLoading &&
  // 预览由后端用环境变量密码解密；解不开的包（历史密码不一致）会在预览阶段报错
  !!props.plan?.success,
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
  selected.value = props.initialFilename
  confirmOverwrite.value = false
  confirmSensitive.value = false
  view.value = 'form'
  if (selected.value) props.onPlan(selected.value)
})

// 终态由父级下传的快照驱动：统一轮询在终态会复位任务状态，不能依赖 task
watch(() => props.result, (r) => {
  if (r) view.value = 'done'
})

function onTryClose() {
  // 还原一旦开跑就不可中断：✕ / 取消 / Esc 全部在这里被挡住（UiDialog 的关闭请求同样走这里）
  if (view.value === 'running') return
  emit('close')
}

/** UiDialog 的关闭请求（Esc / 遮罩 / 内置关闭按钮）统一转成 onTryClose，保留 running 保护 */
function onDialogOpenChange(value: boolean) {
  if (!value) onTryClose()
}

async function doExecute() {
  if (!canExecute.value) return
  view.value = 'running'
  // 入队失败（如后端 409 已有任务在跑）必须回退表单态，否则弹窗永久卡在进度态且无法关闭
  const ok = await props.onExecute(selected.value, {
    confirmSensitive: confirmSensitive.value,
  })
  if (!ok) view.value = 'form'
}
</script>

<style scoped>
.rw-head { display: flex; align-items: center; justify-content: space-between; padding: 20px 24px 0; }
.rw-title { font-size: var(--fs-heading-3); font-weight: 700; color: var(--color-text); margin: 0; letter-spacing: -0.01em; }
.rw-icon-btn { width: 32px; height: 32px; border: 1px solid var(--color-border-light); border-radius: 50%; background: #ffffff; color: var(--color-text-secondary); cursor: pointer; font-size: var(--fs-heading-3); line-height: 1; display: inline-flex; align-items: center; justify-content: center; transition: background 0.2s ease, color 0.2s ease; }
.rw-icon-btn:hover:not(:disabled) { background: var(--color-danger-50); color: var(--color-danger-500); }
.rw-icon-btn:disabled { opacity: .5; cursor: not-allowed; }
.rw-body { padding: 16px 24px 24px; }
.rw-desc { font-size: var(--fs-body-sm); color: var(--color-text-secondary); margin-bottom: 16px; }
.rw-desc-danger { color: var(--color-danger-500); margin-top: 20px; margin-bottom: 12px; }
.rw-file { border: 1px solid var(--color-border-light); border-radius: var(--radius-input, 12px); padding: 9px 12px; font-size: var(--fs-body-sm); color: var(--color-text); background: var(--color-surface); margin-bottom: 16px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rw-loading { font-size: var(--fs-body-sm); color: var(--color-text-muted); margin-bottom: 16px; }
.rw-impact { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 16px; font-size: var(--fs-body-sm); color: var(--color-text); }
.rw-impact b { color: var(--color-primary-700); }
.rw-error { margin-bottom: 16px; color: var(--color-danger-500); font-size: var(--fs-body-sm); }
.rw-danger-list { list-style: none; margin: 0 0 16px; padding: 0; }
.rw-danger-list li { display: flex; align-items: center; gap: 8px; font-size: var(--fs-body-sm); color: var(--color-danger-500); margin-bottom: 8px; }
.rw-danger-list li::before { content: ''; width: 6px; height: 6px; border-radius: 50%; background: var(--color-danger-500); }
.rw-overwrite-check { display: flex; align-items: flex-start; gap: 8px; margin: 4px 0 16px; font-size: var(--fs-body-sm); font-weight: 600; color: var(--color-danger-500); cursor: pointer; }
.rw-overwrite-check input { accent-color: var(--color-danger-500); margin-top: 2px; }
.rw-sensitive-check { display: flex; align-items: flex-start; gap: 8px; margin: 4px 0 16px; font-size: var(--fs-body-sm); color: var(--color-text-secondary); cursor: pointer; }
.rw-sensitive-check input { accent-color: var(--color-primary-600); margin-top: 2px; }
.rw-progress-row { display: flex; align-items: center; gap: 12px; margin: 16px 0; }
.rw-progress { flex: 1; height: 8px; background: var(--color-border-light); border-radius: 999px; overflow: hidden; }
.rw-progress-fill { height: 100%; border-radius: 999px; transition: width .2s ease; }
.rw-fill-processing { background: var(--color-danger-500, #ea5455); }
.rw-fill-danger { background: var(--color-danger-600, #d44042); }
.rw-pct { min-width: 44px; text-align: right; font-variant-numeric: tabular-nums; font-size: var(--fs-body-sm); font-weight: 600; color: var(--color-text-secondary); }
.rw-stage { font-size: var(--fs-body-sm); color: var(--color-text-secondary); }
.rw-report { text-align: center; padding: 24px 0 8px; }
.rw-report-icon { width: 52px; height: 52px; border-radius: 50%; background: var(--color-success-50); color: var(--color-success-500); display: inline-flex; align-items: center; justify-content: center; font-size: 26px; margin-bottom: 12px; }
.rw-report-icon-danger { background: var(--color-danger-50); color: var(--color-danger-500); }
.rw-report-title { font-size: var(--fs-heading-3); font-weight: 700; color: var(--color-text); }
.rw-report-sub { margin-top: 6px; font-size: var(--fs-body-sm); color: var(--color-text-secondary); }
.rw-btn { display: inline-flex; align-items: center; height: 36px; padding: 0 16px; border-radius: var(--radius-button, 14px); font-size: var(--fs-body-sm); font-weight: 600; font-family: inherit; cursor: pointer; border: 2px solid var(--color-border-light); background: #ffffff; color: var(--color-text-secondary); transition: background 0.2s ease, border-color 0.2s ease, color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease; }
.rw-btn:hover:not(:disabled) { border-color: var(--color-primary-300); color: var(--color-primary-700); }
.rw-btn:disabled { opacity: .5; cursor: not-allowed; }
.rw-btn-danger { background: linear-gradient(135deg, var(--color-danger-500), var(--color-danger-600)); color: #fff; border-color: transparent; box-shadow: 0 4px 12px rgba(234, 84, 85, 0.24); }
.rw-btn-danger:hover:not(:disabled) { color: #fff; box-shadow: 0 6px 18px rgba(234, 84, 85, 0.32); transform: translateY(-1px); }
.rw-btn-primary { background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700)); color: #fff; border-color: transparent; box-shadow: 0 4px 12px rgba(91, 141, 239, 0.24); }
.rw-btn-primary:hover:not(:disabled) { color: #fff; box-shadow: 0 6px 18px rgba(91, 141, 239, 0.32); transform: translateY(-1px); }
.mono { font-family: var(--font-mono); }
</style>
