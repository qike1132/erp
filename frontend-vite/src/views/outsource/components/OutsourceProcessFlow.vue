<template>
  <!-- 工序步骤卡片流：直观展示状态流转 -->
  <div v-for="group in processGroups" :key="String(group.itemId)" class="oso-flow">
    <div class="oso-flow-head">
      <span class="oso-flow-sku">{{ group.skuName || 'SKU' }}</span>
      <span class="oso-flow-qty">× {{ group.skuQty }}</span>
    </div>
    <div class="oso-flow-row">
      <template v-for="(p, idx) in group.processes" :key="p.id">
        <div v-if="idx > 0" class="oso-flow-arrow">
          <FontAwesomeIcon icon="angle-right" aria-hidden="true" />
        </div>
        <div :class="['oso-flow-card', `oso-flow-card--${p.status}`]">
          <div class="oso-flow-card-top">
            <span class="oso-flow-seq">{{ idx + 1 }}</span>
            <span class="oso-flow-name">{{ p.process_type }}</span>
            <span :class="['oso-status-badge', `oso-status-${p.status}`]">{{ statusLabel(p.status) }}</span>
          </div>
          <div class="oso-flow-start">
            <span class="oso-flow-start-label">
              <FontAwesomeIcon icon="play-circle" aria-hidden="true" /> 开始
            </span>
            <span class="oso-flow-start-time" :class="p.actual_start_time ? 'oso-flow-start-time--actual' : ''">
              {{ shortDate(p.actual_start_time || p.planned_start_time || '待排期') }}
            </span>
            <span v-if="canManage" class="oso-flow-start-edit">
              <input
                class="oso-dt-input"
                type="datetime-local"
                :value="toDateTimeLocal(p.planned_start_time)"
                title="设置计划开始时间"
                @change="updatePlanned(p, 'planned_start_time', ($event.target as HTMLInputElement).value)"
              />
            </span>
          </div>
          <div class="oso-flow-times">
            <div class="oso-flow-time-row">
              <span class="oso-flow-time-label">完成</span>
              <span class="oso-flow-time-val">
                {{ shortDate(p.actual_end_time || p.planned_end_time || '-') }}
              </span>
              <input
                v-if="canManage"
                class="oso-dt-input oso-dt-input--end"
                type="datetime-local"
                :value="toDateTimeLocal(p.planned_end_time)"
                title="设置计划完成时间"
                @change="updatePlanned(p, 'planned_end_time', ($event.target as HTMLInputElement).value)"
              />
            </div>
          </div>
          <div class="oso-flow-card-actions">
            <UiButton v-if="canManage && p.status !== 'completed'" variant="success" size="sm" @click="handleStart(p)">
              {{ p.status === 'in_progress' ? '完成' : '开始' }}
            </UiButton>
            <UiButton v-if="canManage && p.status !== 'in_progress' && p.status !== 'completed'" variant="outline" size="sm" @click="handleCompleteDirect(p)">
              直接完成
            </UiButton>
            <UiButton v-if="canManage" variant="ghost" size="sm" @click="handleDeleteProcess(p)">
              <FontAwesomeIcon icon="trash" aria-hidden="true" />
            </UiButton>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { OrderOutsourceProcess } from '@/api/outsource'
import UiButton from '@/components/ui/UiButton.vue'
import type { ProcessGroup } from '@/views/outsource/composables/useOutsourceProcess'

defineProps<{
  processGroups: ProcessGroup[]
  canManage: boolean
  statusLabel: (status: string) => string
  shortDate: (v?: string | null) => string
  toDateTimeLocal: (v?: string | null) => string
  updatePlanned: (p: OrderOutsourceProcess, field: 'planned_start_time' | 'planned_end_time', value: string) => Promise<void>
  handleStart: (p: OrderOutsourceProcess) => Promise<void>
  handleCompleteDirect: (p: OrderOutsourceProcess) => Promise<void>
  handleDeleteProcess: (p: OrderOutsourceProcess) => Promise<void>
}>()
</script>

<style scoped>
.oso-flow {
  border: 1px solid #e8ecf1;
  border-radius: 12px;
  padding: 12px 14px;
  background: #fcfdfe;
}
.oso-flow-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.oso-flow-sku { font-weight: 700; font-size: 13.5px; color: var(--color-text); }
.oso-flow-qty { font-size: 12px; color: var(--color-text-muted); }
.oso-flow-row {
  display: flex;
  align-items: stretch;
  gap: 0;
  overflow-x: auto;
  padding-bottom: 4px;
}
.oso-flow-arrow {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #cbd5e1;
  font-size: 16px;
  padding: 0 6px;
  flex-shrink: 0;
}
.oso-flow-card {
  flex-shrink: 0;
  width: 220px;
  border: 1.5px solid #e2e8f0;
  border-radius: 12px;
  padding: 10px 12px;
  background: white;
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: box-shadow 0.15s ease, border-color 0.15s ease, transform 0.15s ease;
}
.oso-flow-card:hover { box-shadow: 0 2px 10px rgba(0,0,0,0.08); transform: translateY(-1px); }
.oso-flow-card--pending { border-color: #e2e8f0; }
.oso-flow-card--in_progress {
  border-color: var(--color-primary-400);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.10);
}
.oso-flow-card--completed {
  border-color: var(--color-success-400);
  background: #f6fdf8;
}
.oso-flow-card-top {
  display: flex;
  align-items: center;
  gap: 7px;
}
.oso-flow-seq {
  width: 22px;
  height: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 7px;
  background: #f1f5f9;
  color: var(--color-text-muted);
  font-size: 11.5px;
  font-weight: 700;
  flex-shrink: 0;
}
.oso-flow-card--in_progress .oso-flow-seq { background: var(--color-primary-50); color: var(--color-primary-600); }
.oso-flow-card--completed .oso-flow-seq { background: var(--color-success-100); color: var(--color-success-700); }
.oso-flow-name {
  font-size: 13px;
  font-weight: 700;
  color: var(--color-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.oso-flow-start {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 3px;
  padding: 8px 10px;
  background: var(--color-primary-50);
  border-radius: 9px;
  border: 1px solid var(--color-primary-100);
}
.oso-flow-card--completed .oso-flow-start {
  background: var(--color-success-50);
  border-color: var(--color-success-100);
}
.oso-flow-start-label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 10.5px;
  font-weight: 700;
  color: var(--color-primary-600);
}
.oso-flow-card--completed .oso-flow-start-label { color: var(--color-success-700); }
.oso-flow-start-time {
  font-size: 16px;
  font-weight: 800;
  color: var(--color-primary-700);
  line-height: 1.2;
  white-space: nowrap;
}
.oso-flow-card--completed .oso-flow-start-time { color: var(--color-success-700); }
.oso-flow-start-time--actual { color: var(--color-text); }
.oso-flow-start-edit { width: 100%; }

.oso-flow-times {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.oso-flow-time-row {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
}
.oso-flow-time-label {
  color: var(--color-text-muted);
  font-size: 10.5px;
  font-weight: 600;
  flex-shrink: 0;
  width: 24px;
}
.oso-flow-time-val {
  color: var(--color-text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
}
.oso-dt-input {
  flex: 1;
  min-width: 0;
  padding: 3px 6px;
  font-size: 11px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background: white;
  color: var(--color-text);
  box-sizing: border-box;
}
.oso-dt-input--end { max-width: 105px; }
.oso-dt-input:focus { outline: 2px solid var(--color-primary-500); outline-offset: 1px; border-color: var(--color-primary-400); }
.oso-flow-card-actions {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: auto;
}

.oso-status-badge {
  display: inline-block;
  padding: 2px 9px;
  border-radius: 7px;
  font-size: 11.5px;
  font-weight: 600;
  white-space: nowrap;
}
.oso-status-pending { background: var(--color-warning-50); color: var(--color-warning-600); }
.oso-status-in_progress { background: var(--color-primary-50); color: var(--color-primary-600); }
.oso-status-completed { background: var(--color-success-50); color: var(--color-success-700); }
</style>