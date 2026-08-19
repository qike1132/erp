<template>
  <UiDialog v-model:open="detailOpen" title="订单外发工序" max-width-class="max-w-[1180px]">
    <div v-if="detailData" class="oso-detail">
      <div class="oso-detail-head">
        <div class="oso-detail-meta">
          <span class="oso-detail-no">{{ detailData.order_no || '-' }}</span>
          <span class="oso-detail-meta-item"><span class="oso-detail-meta-label">客户</span>{{ detailData.customer || '-' }}</span>
          <span class="oso-detail-meta-item"><span class="oso-detail-meta-label">下单</span>{{ detailData.order_date || '-' }}</span>
          <span class="oso-detail-meta-item"><span class="oso-detail-meta-label">数量</span><strong class="oso-detail-meta-num">{{ detailTotalQuantity }}</strong></span>
        </div>
        <div class="oso-detail-overview">
          <div class="oso-detail-progress">
            <UiProgressBar :percent="detailProgress" :variant="progressVariant(detailProgress)" />
          </div>
          <span class="oso-detail-progress-text">
            <strong>{{ detailProgress }}%</strong>
            <span>{{ completedProcesses }}/{{ totalProcesses }} 道完成</span>
          </span>
          <span v-if="totalProcesses > 0" :class="['oso-status-badge', `oso-status-${detailStatusClass}`]">{{ detailStatusLabel }}</span>
        </div>
      </div>

      <div v-if="isStockinRecord" class="oso-detail-actions">
        <span class="oso-detail-hint">备货记录不参与外发工序管理，请在订单记录上操作</span>
      </div>
      <div v-else-if="canManage" class="oso-detail-actions">
        <UiButton variant="primary" size="sm" :disabled="generating" @click="handleGenerate">
          <FontAwesomeIcon icon="wand-magic-sparkles" aria-hidden="true" /> {{ generating ? '生成中…' : '按SKU预设生成工序' }}
        </UiButton>
        <span class="oso-detail-hint">返单时系统已按 SKU 预设自动带出工序，可在此补生成</span>
      </div>

      <div v-if="loadingProcesses" class="oso-empty">
        <UiSpinner />
      </div>
      <template v-else>
        <div v-if="processRows.length === 0" class="oso-empty">
          <FontAwesomeIcon icon="route" aria-hidden="true" />
          <span v-if="isStockinRecord">备货记录无外发工序，仅订单参与外发流程</span>
          <span v-else>该订单尚未配置外发工序{{ canManage ? '，可点击上方按钮按 SKU 预设生成' : '' }}</span>
        </div>
        <OutsourceProcessFlow
          v-else
          :process-groups="processGroups"
          :can-manage="canManage"
          :status-label="statusLabel"
          :short-date="shortDate"
          :to-date-time-local="toDateTimeLocal"
          :update-planned="updatePlanned"
          :handle-start="handleStart"
          :handle-complete-direct="handleCompleteDirect"
          :handle-delete-process="handleDeleteProcess"
        />
      </template>
    </div>
    <template #footer>
      <UiButton variant="outline" @click="detailOpen = false">关闭</UiButton>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import { toRef, watch } from 'vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import UiProgressBar from '@/components/ui/UiProgressBar.vue'
import OutsourceProcessFlow from './OutsourceProcessFlow.vue'
import { useOutsourceProcess } from '@/views/outsource/composables/useOutsourceProcess'
import type { OutsourceOrderRow } from '@/views/outsource/composables/useOutsourceOrders'

const props = defineProps<{
  detailData: OutsourceOrderRow | null
}>()

const emit = defineEmits<{
  refresh: []
}>()

const detailOpen = defineModel<boolean>('open', { default: false })

const detailDataRef = toRef(props, 'detailData')

const {
  canManage,
  loadingProcesses,
  generating,
  isStockinRecord,
  detailTotalQuantity,
  totalProcesses,
  completedProcesses,
  detailProgress,
  detailStatusLabel,
  detailStatusClass,
  processGroups,
  processRows,
  progressVariant,
  loadProcesses,
  handleGenerate,
  handleStart,
  handleCompleteDirect,
  handleDeleteProcess,
  updatePlanned,
  toDateTimeLocal,
  statusLabel,
  shortDate,
} = useOutsourceProcess(detailDataRef, emit)

watch([detailOpen, detailDataRef], ([open, data]) => {
  if (open && data) loadProcesses(data.id)
})
</script>

<style scoped>
.oso-detail {
  display: flex;
  flex-direction: column;
  gap: 14px;
  font-size: 14px;
  color: var(--color-text);
}

.oso-detail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding: 12px 16px;
  background: #f8fafc;
  border: 1px solid #e8ecf1;
  border-radius: 12px;
}
.oso-detail-meta {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  min-width: 0;
}
.oso-detail-no {
  font-weight: 700;
  font-size: 15px;
  color: var(--color-text);
  white-space: nowrap;
}
.oso-detail-meta-item { display: inline-flex; align-items: center; gap: 4px; white-space: nowrap; font-size: 13px; }
.oso-detail-meta-label { color: var(--color-text-muted, #64748b); font-size: 12px; }
.oso-detail-meta-num { color: var(--color-primary-700, #2d5ab8); }
.oso-detail-overview {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}
.oso-detail-progress { width: 140px; }
.oso-detail-progress-text {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  font-size: 12px;
  color: var(--color-text-muted);
  white-space: nowrap;
}
.oso-detail-progress-text strong { font-size: 16px; color: var(--color-primary-600); }

.oso-detail-actions { display: flex; align-items: center; gap: 12px; }
.oso-detail-hint { font-size: 12px; color: var(--color-text-muted); }

.oso-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-text-muted);
}
.oso-empty span { font-size: 14px; }

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
