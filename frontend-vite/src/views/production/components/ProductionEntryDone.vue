<template>
  <div class="pr-done" data-test="qe-done">
    <div class="pr-done-hero">
      <span class="pr-done-icon"><FontAwesomeIcon icon="check" aria-hidden="true" /></span>
      <div>
        <h3>已录入 {{ created.length }} 条生产记录</h3>
        <p>{{ deptLabel }} · {{ date }} · 合计 {{ totalQty }} 件 / {{ formatCurrency(totalValue) }}</p>
      </div>
    </div>

    <div class="pr-done-list">
      <div v-for="item in created" :key="item.id" class="pr-done-row">
        <span class="nm" :title="item.product_name">{{ item.product_name }}</span>
        <span v-if="item.batch_no" class="bt">{{ item.batch_no }}</span>
        <span class="qt">{{ item.quantity }} 件</span>
        <span class="vl">{{ formatCurrency((item.quantity || 0) * (item.unit_price || 0)) }}</span>
      </div>
    </div>

    <div class="pr-done-note">
      <FontAwesomeIcon icon="info-circle" aria-hidden="true" />
      <span>按 SKU 逐条落库。若这一批录错了，可整批撤销（物理删除，需二次确认）。</span>
    </div>

    <div class="pr-done-actions">
      <button type="button" class="pr-done-btn pri" data-test="qe-again" @click="emit('again')">
        <FontAwesomeIcon icon="plus" aria-hidden="true" /> 再录一批
      </button>
      <button type="button" class="pr-done-btn" data-test="qe-finish" @click="emit('close')">完成</button>
      <button type="button" class="pr-done-btn danger" data-test="qe-undo" @click="emit('undo')">
        <FontAwesomeIcon icon="undo" aria-hidden="true" /> 撤销本批
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
/** ProductionEntryDone — 批量提交成功后的回执页（整批可撤销） */
import { computed } from 'vue'
import { formatCurrency } from '@/utils/format'
import type { CreatedRecordSummary } from '../composables/useProductionEntry'

const props = defineProps<{
  created: CreatedRecordSummary[]
  deptLabel: string
  date: string
}>()

const emit = defineEmits<{
  again: []
  close: []
  undo: []
}>()

const totalQty = computed(() => props.created.reduce((s, c) => s + (c.quantity || 0), 0))
const totalValue = computed(() => props.created.reduce((s, c) => s + (c.quantity || 0) * (c.unit_price || 0), 0))
</script>

<style scoped>
.pr-done { flex: 1; min-height: 0; overflow: auto; padding: 26px 30px; display: flex; flex-direction: column; gap: 16px; }
.pr-done-hero { display: flex; align-items: center; gap: 16px; }
.pr-done-icon { width: 54px; height: 54px; flex: 0 0 54px; border-radius: 16px; background: var(--color-success-50); border: 1px solid var(--color-success-300); color: var(--color-success-600); display: grid; place-items: center; font-size: 26px; }
.pr-done-hero h3 { margin: 0; font-size: 20px; font-weight: 800; }
.pr-done-hero p { margin: 5px 0 0; font-size: 16px; color: var(--color-text-muted); }
.pr-done-list { border: 1px solid var(--color-border); border-radius: 12px; overflow: hidden; }
.pr-done-row { display: flex; align-items: center; gap: 12px; padding: 12px 16px; border-bottom: 1px solid var(--color-border-light); font-size: 16px; }
.pr-done-row:last-child { border-bottom: none; }
.pr-done-row .nm { flex: 1; min-width: 0; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pr-done-row .bt { font-family: var(--font-mono); font-size: 14px; color: var(--color-text-muted); background: var(--color-surface); border-radius: 5px; padding: 1px 7px; }
.pr-done-row .qt { font-weight: 800; font-variant-numeric: tabular-nums; color: var(--color-text-secondary); }
.pr-done-row .vl { width: 110px; text-align: right; font-variant-numeric: tabular-nums; color: var(--color-text-muted); }
.pr-done-note { display: flex; align-items: flex-start; gap: 9px; padding: 12px 15px; border-radius: 10px; background: var(--color-primary-50); border: 1px solid var(--color-primary-200); color: var(--color-primary-800); font-size: 14px; line-height: 1.6; }
.pr-done-actions { display: flex; align-items: center; gap: 10px; }
.pr-done-btn { display: inline-flex; align-items: center; gap: 8px; height: 46px; padding: 0 20px; border-radius: 10px; border: 1px solid var(--color-border); background: #fff; color: var(--color-text-secondary); font-size: 16px; font-weight: 700; cursor: pointer; font-family: inherit; }
.pr-done-btn.pri { background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700)); border-color: transparent; color: #fff; }
.pr-done-btn.danger { margin-left: auto; color: var(--color-danger-600); border-color: var(--color-danger-300); }
.pr-done-btn.danger:hover { background: var(--color-danger-50); }
</style>
