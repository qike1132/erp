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
.sc-card { border: 1px solid var(--color-border, #e5e6eb); border-radius: 8px; background: var(--color-surface, #fff); padding: 20px; }
.sc-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 12px 0; border-bottom: 1px solid var(--color-surface-muted, #f2f3f5); }
.sc-label { font-size: 14px; }
.sc-switch { position: relative; width: 36px; height: 20px; border-radius: 999px; background: var(--color-border-strong, #c9cdd4); border: none; cursor: pointer; }
.sc-switch::after { content: ''; position: absolute; top: 2px; left: 2px; width: 16px; height: 16px; border-radius: 50%; background: #fff; transition: left .15s ease; }
.sc-switch.on { background: var(--color-primary, #2f7bff); }
.sc-switch.on::after { left: 18px; }
.sc-select, .sc-input { height: 32px; padding: 0 12px; border: 1px solid var(--color-border-strong, #c9cdd4); border-radius: 6px; font-size: 14px; }
.sc-actns { display: flex; gap: 12px; margin-top: 16px; }
.sc-btn { height: 32px; padding: 0 16px; border-radius: 6px; font-size: 14px; cursor: pointer; border: 1px solid transparent; }
.sc-btn-primary { background: var(--color-primary, #2f7bff); color: #fff; }
.sc-btn-primary:disabled { background: var(--color-surface-muted, #f2f3f5); color: var(--color-text-disabled, #c9cdd4); cursor: not-allowed; }
.sc-btn-outline { background: transparent; border-color: var(--color-border, #e5e6eb); color: var(--color-text-secondary, #4e5969); }
.mono { font-family: var(--font-mono, Consolas, monospace); }
.sc-list { margin-top: 16px; display: flex; flex-direction: column; gap: 8px; }
.sc-item { display: flex; align-items: center; gap: 12px; border: 1px solid var(--color-border, #e5e6eb); border-radius: 8px; padding: 10px 14px; font-size: 13px; }
.sc-item-name { font-weight: 500; }
.sc-item-cron { color: var(--color-text-tertiary, #86909c); flex: 1; }
.sc-item-status { font-size: 12px; color: var(--color-text-tertiary, #86909c); }
.sc-item-del { border: none; background: none; color: var(--color-danger, #ef4444); cursor: pointer; }
.sc-empty { font-size: 13px; color: var(--color-text-tertiary, #86909c); }
</style>