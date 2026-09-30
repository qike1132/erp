<template>
  <div class="pr-detail" data-test="qe-detail">
    <label class="pr-detail-field">
      <span class="pr-detail-label">日期</span>
      <input
        :value="date"
        type="date"
        class="pr-detail-input"
        aria-label="生产日期"
        @input="emit('update:date', readValue($event))"
      />
    </label>
    <label class="pr-detail-field">
      <span class="pr-detail-label">单价</span>
      <input
        :value="unitPrice"
        type="number"
        min="0"
        step="0.01"
        inputmode="decimal"
        class="pr-detail-input"
        placeholder="0.00"
        aria-label="单价"
        @input="emit('update:unitPrice', Number(readValue($event)) || 0)"
      />
    </label>
    <label class="pr-detail-field">
      <span class="pr-detail-label">产值</span>
      <span class="pr-detail-value">{{ formatCurrency(value) }}</span>
    </label>
    <label class="pr-detail-field pr-detail-field-wide">
      <span class="pr-detail-label">备注</span>
      <input
        :value="remark"
        type="text"
        class="pr-detail-input"
        placeholder="选填，例如批次号或特殊说明"
        aria-label="备注"
        @input="emit('update:remark', readValue($event))"
      />
    </label>
  </div>
</template>

<script setup lang="ts">
/**
 * EntryDetailFields — 录入弹窗「详细」里被折叠的慢路径字段。
 *
 * 从快捷行剥离出来：日期默认取选中日、单价由选品自动带出，只有补录备注 / 改单价 /
 * 改日期时才需要展开。单独成组件是为了让快捷录入的弹窗主体留在 400 行门禁之下。
 */
import { formatCurrency } from '@/utils/format'

defineProps<{
  date: string
  unitPrice: number
  value: number
  remark: string
}>()

const emit = defineEmits<{
  'update:date': [value: string]
  'update:unitPrice': [value: number]
  'update:remark': [value: string]
}>()

function readValue(event: Event): string {
  return (event.target as HTMLInputElement).value
}
</script>

<style scoped>
.pr-detail { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; padding: 14px; border: 1px solid var(--color-border-light); border-radius: 12px; background: var(--color-surface); }
.pr-detail-field { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.pr-detail-field-wide { grid-column: 1 / -1; }
.pr-detail-label { font-size: 11px; font-weight: 700; color: var(--color-text-secondary); letter-spacing: 0.03em; }
.pr-detail-input { width: 100%; padding: 10px 14px; font-size: 14px; line-height: 1.5; color: var(--color-text); background: white; border: 1px solid var(--color-border); border-radius: 10px; transition: border-color 0.2s ease, box-shadow 0.2s ease; outline: none; min-height: 44px; box-sizing: border-box; font-family: inherit; }
.pr-detail-input:hover { border-color: var(--color-border-strong); }
.pr-detail-input:focus { border-color: var(--color-primary-500); box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.12); }
.pr-detail-input::placeholder { color: var(--color-text-placeholder); }
.pr-detail-value { display: flex; align-items: center; min-height: 44px; padding: 10px 14px; border-radius: 10px; background: linear-gradient(135deg, var(--color-primary-50) 0%, var(--color-primary-100) 100%); border: 1px solid var(--color-primary-200); font-size: 17px; font-weight: 800; color: var(--color-primary-700); font-variant-numeric: tabular-nums; }
@media (max-width: 900px) {
  .pr-detail { grid-template-columns: 1fr; }
}
</style>
