<template>
  <header class="pr-toolbar">
    <div class="pr-toolbar-row pr-toolbar-row-right">
      <div class="pr-tab-group" role="tablist">
        <button role="tab" :aria-selected="viewTab === 'daily'" :class="['pr-tab', { 'pr-tab-active': viewTab === 'daily' }]" aria-label="日报" @click="emit('update:viewTab', 'daily')">日报</button>
        <button role="tab" :aria-selected="viewTab === 'monthly'" :class="['pr-tab', { 'pr-tab-active': viewTab === 'monthly' }]" aria-label="月报" @click="emit('update:viewTab', 'monthly')">月报</button>
      </div>
      <div class="pr-toolbar-controls">
        <div v-if="viewTab !== 'monthly'" class="pr-date-nav">
          <button class="pr-date-btn" aria-label="上一页" @click="emit('prev-day')"><FontAwesomeIcon icon="chevron-left" aria-hidden="true" /></button>
          <input v-model="dateRefModel" type="date" class="pr-date-input" aria-label="日期选择" />
          <button class="pr-date-btn" aria-label="下一页" @click="emit('next-day')"><FontAwesomeIcon icon="chevron-right" aria-hidden="true" /></button>
          <button class="pr-today-btn" aria-label="今天" @click="emit('today')">今天</button>
        </div>
        <div v-else class="pr-date-nav">
          <button class="pr-date-btn" aria-label="上一月" @click="emit('prev-month')"><FontAwesomeIcon icon="chevron-left" aria-hidden="true" /></button>
          <span class="pr-month-label">{{ monthlyYear }}年{{ monthlyMonth }}月</span>
          <button class="pr-date-btn" aria-label="下一月" @click="emit('next-month')"><FontAwesomeIcon icon="chevron-right" aria-hidden="true" /></button>
        </div>
        <div class="pr-divider" />
        <div class="pr-actions-group">
          <button class="pr-action-btn pr-action-primary" aria-label="录入" @click="emit('open-entry')">
            <FontAwesomeIcon icon="plus" aria-hidden="true" /> 录入
          </button>
          <button class="pr-action-btn" aria-label="导出" @click="emit('export')">
            <FontAwesomeIcon icon="download" aria-hidden="true" /> 导出
          </button>
        </div>
      </div>
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  viewTab: string
  dateRef: string
  monthlyYear: number
  monthlyMonth: number
}>()

const emit = defineEmits<{
  'update:viewTab': [value: string]
  'update:dateRef': [value: string]
  'prev-day': []
  'next-day': []
  'prev-month': []
  'next-month': []
  'today': []
  'open-entry': []
  'export': []
}>()

const dateRefModel = computed({
  get: () => props.dateRef,
  set: (v: string) => emit('update:dateRef', v),
})
</script>

<style scoped>
.pr-toolbar { padding: 14px 24px 10px; background: white; border-bottom: 1px solid #f1f5f9; flex-shrink: 0; }
.pr-toolbar-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; width: 100%; }
.pr-toolbar-row-right { justify-content: space-between; flex-wrap: nowrap; }
.pr-toolbar-controls { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.pr-actions-group { display: flex; align-items: center; gap: 8px; flex-shrink: 0; padding: 3px; border-radius: 10px; background: #f1f5f9; border: 1px solid #e2e8f0; }
.pr-actions-group .pr-action-btn { background: transparent; border: 1px solid transparent; box-shadow: none; }
.pr-actions-group .pr-action-primary { background: transparent; border-color: transparent; color: #1e40af; }
.pr-divider { width: 1px; height: 20px; background: #e2e8f0; flex-shrink: 0; }

.pr-date-nav { display: flex; align-items: center; gap: 6px; }
.pr-date-btn { width: 32px; height: 32px; border: 1px solid #e2e8f0; border-radius: 8px; background: white; cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 11px; color: #64748b; transition: all 0.2s ease; }
.pr-date-btn:hover { border-color: #3b82f6; color: #1e40af; background: #eff6ff; }
.pr-date-input { padding: 6px 10px; border: 1px solid #e2e8f0; border-radius: 8px; font-size: 13px; font-weight: 600; color: #1e293b; background: white; cursor: pointer; transition: border-color 0.2s ease; }
.pr-date-input:hover { border-color: #3b82f6; }
.pr-today-btn { padding: 6px 12px; border: 1px solid #bfdbfe; border-radius: 8px; background: #eff6ff; font-size: 12px; font-weight: 600; color: #1e40af; cursor: pointer; transition: all 0.2s ease; }
.pr-today-btn:hover { background: #dbeafe; }
.pr-month-label { font-size: 15px; font-weight: 700; color: #1e293b; min-width: 100px; text-align: center; }

.pr-tab-group { display: inline-flex; gap: 4px; padding: 4px; border-radius: 12px; background: white; border: 1px solid var(--color-border-light, #e2e8f0); box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06); }
.pr-tab { padding: 8px 14px; border: none; border-radius: 9px; background: transparent; font-size: 13px; font-weight: 600; color: var(--color-text-secondary); cursor: pointer; transition: background 0.3s ease, color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease; display: inline-flex; align-items: center; justify-content: center; gap: 6px; }
.pr-tab:hover { background: var(--color-primary-50); color: var(--color-primary-600); box-shadow: 0 4px 12px rgba(0,0,0,0.08); transform: translateY(-1px); }
.pr-tab-active { background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100)); color: var(--color-primary-700); box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91,141,239,0.2); transform: translateY(-1px); }

.pr-action-btn { padding: 7px 14px; border: 1px solid #e2e8f0; border-radius: 8px; background: white; font-size: 12px; font-weight: 600; cursor: pointer; color: #475569; display: inline-flex; align-items: center; gap: 5px; transition: all 0.2s ease; }
.pr-action-btn:hover { border-color: #3b82f6; color: #1e40af; background: #eff6ff; }
.pr-action-primary { color: #1e40af; border-color: #bfdbfe; background: #eff6ff; }
.pr-action-primary:hover { background: #dbeafe; border-color: #3b82f6; }

@media (max-width: 1024px) {
  .pr-toolbar { padding: 12px 16px 8px; }
}
@media (max-width: 768px) {
  .pr-toolbar { padding: 10px 12px 8px; }
  .pr-toolbar-row { gap: 8px; }
  .pr-toolbar-row-right { flex-wrap: wrap; justify-content: flex-end; }
  .pr-toolbar-controls { flex-wrap: wrap; overflow-x: auto; }
  .pr-divider { display: none; }
}
</style>
