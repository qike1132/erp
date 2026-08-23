<template>
  <div class="sc-card">
    <div class="sc-row">
      <div class="sc-label">启用定时备份</div>
      <button class="sc-switch" :class="{ on: form.enabled }" role="switch" :aria-checked="form.enabled" @click="form.enabled = !form.enabled"></button>
    </div>
    <div class="sc-row">
      <div class="sc-label">备份周期</div>
      <select v-model="period" class="sc-select">
        <option value="daily">每日</option>
        <option value="weekly">每周</option>
        <option value="monthly">每月</option>
        <option value="custom">自定义 cron</option>
      </select>
    </div>
    <div v-if="period === 'custom'" class="sc-row">
      <div class="sc-label">cron 表达式</div>
      <input v-model="form.cron_expr" class="sc-input mono" placeholder="0 2 * * *" />
    </div>
    <div v-if="period === 'daily'" class="sc-row">
      <div class="sc-label">执行时间</div>
      <input v-model="timeInput" type="time" class="sc-input" />
    </div>
    <div class="sc-actions">
      <button class="sc-btn sc-btn-primary" :disabled="saving" @click="handleSave">{{ saving ? '保存中...' : '保存配置' }}</button>
      <button class="sc-btn sc-btn-outline" @click="onTrigger">立即触发一次</button>
    </div>
    <div class="sc-list">
      <div v-for="s in schedules" :key="String(s.id ?? s.name)" class="sc-item">
    <span class="sc-item-name">{{ s.name }}</span>
    <span class="sc-item-cron mono">{{ s.cron_expr || s.schedule }}</span>
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
const form = reactive({ enabled: true, cron_expr: '0 2 * * *' })

watch(period, (p) => {
  if (p === 'daily') form.cron_expr = `0 ${timeInput.value.split(':')[0]} * * *`
})

function handleSave() {
  const hour = parseInt(timeInput.value.split(':')[0] || '2', 10)
  const cron = period.value === 'daily' ? `0 ${hour} * * *`
    : period.value === 'weekly' ? `0 ${hour} * * 1`
    : period.value === 'monthly' ? `0 ${hour} 1 * *`
    : form.cron_expr.trim() || '0 2 * * *'
  props.onSave({ name: '自定义备份', task_type: 'incremental', cron_expr: cron, enabled: form.enabled })
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