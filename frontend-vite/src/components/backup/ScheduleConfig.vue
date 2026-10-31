<template>
  <div class="sc-card">
    <div class="sc-row">
      <div class="sc-label">启用定时备份</div>
      <button
        class="sc-switch"
        :class="{ on: form.enabled }"
        type="button"
        role="switch"
        aria-label="启用定时备份"
        :aria-checked="form.enabled"
        @click="form.enabled = !form.enabled"
      />
    </div>
    <div class="sc-row">
      <div class="sc-label">任务类型</div>
      <select v-model="taskType" class="sc-select" aria-label="任务类型">
        <option value="full">全量备份</option>
        <option value="integrity_check">完整性巡检</option>
        <option value="cleanup">智能清理</option>
        <option value="disaster_recovery_test">灾备恢复演练</option>
      </select>
    </div>
    <div class="sc-row">
      <div class="sc-label">备份周期</div>
      <select v-model="period" class="sc-select" aria-label="备份周期">
        <option value="daily">每日</option>
        <option value="weekly">每周</option>
        <option value="monthly">每月</option>
        <option value="custom">自定义 cron</option>
      </select>
    </div>
    <div v-if="period === 'custom'" class="sc-row">
      <div class="sc-label">cron 表达式</div>
      <input v-model="form.cron_expr" class="sc-input mono" placeholder="0 2 * * *" aria-label="cron 表达式" />
    </div>
    <div v-if="period === 'daily'" class="sc-row">
      <div class="sc-label">执行时间</div>
      <input v-model="timeInput" type="time" class="sc-input" aria-label="执行时间" />
    </div>
    <div class="sc-actions">
      <button class="sc-btn sc-btn-primary" :disabled="saving" @click="handleSave">{{ saving ? '保存中...' : '保存配置' }}</button>
      <button class="sc-btn sc-btn-outline" @click="onTrigger">立即触发一次</button>
    </div>
    <div class="sc-list">
      <div v-for="s in schedules" :key="String(s.id ?? s.name)" class="sc-item">
        <span class="sc-item-name">{{ s.name }}</span>
        <span class="sc-item-cron mono" :title="s.cron_expr || s.schedule || ''">{{ cronLabel(s.cron_expr || s.schedule) }}</span>
        <span class="sc-item-status">{{ s.enabled ? '已启用' : '已停用' }}</span>
        <button class="sc-item-del" title="删除" @click="s.id != null && onDelete(s.id)">删除</button>
      </div>
      <div v-if="schedules.length === 0" class="sc-empty">暂无定时任务</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import type { BackupScheduleItem } from '@/api/backup'

const props = defineProps<{
  schedules: BackupScheduleItem[]
  saving?: boolean
  onSave: (data: { name: string; task_type: string; cron_expr: string; enabled: boolean }) => void
  onDelete: (id: number) => void
  onTrigger: () => void
}>()

const period = ref<'daily' | 'weekly' | 'monthly' | 'custom'>('daily')
const timeInput = ref('02:00')
const taskType = ref('full')
const form = reactive({ enabled: true, cron_expr: '0 2 * * *' })

const TASK_TYPE_LABELS: Record<string, string> = {
  full: '全量备份',
  integrity_check: '完整性巡检',
  cleanup: '智能清理',
  disaster_recovery_test: '灾备恢复演练',
}

const WEEKDAY_LABELS = ['日', '一', '二', '三', '四', '五', '六']

/** 把 5 段 cron（分 时 日 月 周）转成中文时间描述，悬停可看原文。
 *  只翻译本页会产生/常见的「纯数字或 *」形态；带步进、区间、月份的表达式原样回退。 */
function cronLabel(expr?: string | null) {
  const raw = (expr ?? '').trim()
  const m = raw.match(/^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)$/)
  if (!m) return raw
  const [, min = '', hour = '', dom = '', mon = '', dow = ''] = m
  if (mon !== '*' || !/^\d{1,2}$/.test(hour) || !/^\d{1,2}$/.test(min)) return raw
  const time = `${hour.padStart(2, '0')}:${min.padStart(2, '0')}`
  if (dom === '*' && dow === '*') return `每天 ${time}`
  if (dom === '*' && /^\d$/.test(dow)) return `每周${WEEKDAY_LABELS[Number(dow) % 7]} ${time}`
  if (dow === '*' && /^\d{1,2}$/.test(dom)) return `每月${Number(dom)}日 ${time}`
  return raw
}

/** timeInput("HH:MM") → (小时, 分钟)；type=time 清空时回退 02:00。
 *  分钟必须进 cron：此前只取小时、分钟硬编码 0，用户选 08:27 保存成 `0 8 * * *`。 */
function timeParts(): [number, number] {
  const [h = '', m = ''] = timeInput.value.split(':')
  const hh = Number.parseInt(h, 10)
  const mm = Number.parseInt(m, 10)
  return [
    Number.isNaN(hh) ? 2 : Math.min(Math.max(hh, 0), 23),
    Number.isNaN(mm) ? 0 : Math.min(Math.max(mm, 0), 59),
  ]
}

watch(period, (p) => {
  if (p === 'daily') {
    const [hh, mm] = timeParts()
    form.cron_expr = `${mm} ${hh} * * *`
  }
})

function handleSave() {
  const [hh, mm] = timeParts()
  const cron = period.value === 'daily' ? `${mm} ${hh} * * *`
    : period.value === 'weekly' ? `${mm} ${hh} * * 1`
    : period.value === 'monthly' ? `${mm} ${hh} 1 * *`
    : form.cron_expr.trim() || '0 2 * * *'
  const typeLabel = TASK_TYPE_LABELS[taskType.value] ?? '自定义'
  props.onSave({ name: `自定义${typeLabel}`, task_type: taskType.value, cron_expr: cron, enabled: form.enabled })
}
</script>

<style scoped>
.sc-card { border: 1px solid var(--color-border-light); border-radius: var(--radius-md, 14px); background: #ffffff; padding: 24px; box-shadow: 0 1px 3px rgba(0,0,0,.04), 0 4px 12px rgba(0,0,0,.06); }
.sc-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 12px 0; border-bottom: 1px solid var(--color-border-light); }
.sc-label { font-size: 14px; color: var(--color-text); }
.sc-switch { position: relative; width: 38px; height: 22px; border-radius: 999px; background: var(--color-border); border: none; cursor: pointer; transition: background 0.2s ease; flex-shrink: 0; }
.sc-switch::after { content: ''; position: absolute; top: 2px; left: 2px; width: 18px; height: 18px; border-radius: 50%; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,.2); transition: left .15s ease; }
.sc-switch.on { background: var(--color-primary-600); }
.sc-switch.on::after { left: 18px; }
.sc-select, .sc-input { height: 36px; padding: 0 12px; border: 1px solid var(--color-border-light); border-radius: var(--radius-input, 12px); font-size: 14px; font-family: inherit; color: var(--color-text); background: #ffffff; transition: border-color 0.2s ease, box-shadow 0.2s ease; }
.sc-select:focus, .sc-input:focus { outline: none; border-color: var(--color-primary-300); box-shadow: 0 0 0 3px var(--color-primary-50); }
.sc-actions { display: flex; gap: 12px; margin-top: 16px; }
.sc-btn { display: inline-flex; align-items: center; height: 36px; padding: 0 16px; border: 2px solid transparent; border-radius: var(--radius-button, 14px); font-size: 13px; font-weight: 600; font-family: inherit; cursor: pointer; transition: background 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease, border-color 0.2s ease, color 0.2s ease; }
.sc-btn-primary { background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700)); color: #fff; box-shadow: 0 4px 12px rgba(91, 141, 239, 0.24); }
.sc-btn-primary:disabled { background: var(--color-border-light); color: var(--color-text-muted); cursor: not-allowed; box-shadow: none; }
.sc-btn-primary:hover:not(:disabled) { box-shadow: 0 6px 18px rgba(91, 141, 239, 0.32); transform: translateY(-1px); }
.sc-btn-outline { background: #ffffff; border-color: var(--color-border-light); color: var(--color-primary-600); }
.sc-btn-outline:hover { border-color: var(--color-primary-300); background: var(--color-primary-50); color: var(--color-primary-700); }
.mono { font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace; }
.sc-list { margin-top: 16px; display: flex; flex-direction: column; gap: 8px; }
.sc-item { display: flex; align-items: center; gap: 12px; border: 1px solid var(--color-border-light); border-radius: var(--radius-sm, 10px); padding: 10px 14px; font-size: 13px; background: #ffffff; }
.sc-item-name { font-weight: 600; color: var(--color-text); }
.sc-item-cron { color: var(--color-text-muted); flex: 1; }
.sc-item-status { font-size: 12px; color: var(--color-text-secondary); }
.sc-item-del { border: none; background: none; color: var(--color-danger-500); cursor: pointer; font-family: inherit; }
.sc-empty { font-size: 13px; color: var(--color-text-muted); }
</style>