<template>
  <UiDialog v-model:open="detailOpen" title="订单外发工序" max-width-class="max-w-[1180px]">
    <div v-if="detailData" class="oso-detail">
      <div class="oso-detail-head">
        <div class="oso-detail-meta">
          <span class="oso-detail-no">{{ detailData.order_no || '-' }}</span>
          <span class="oso-detail-meta-item"><span class="oso-detail-meta-label">客户</span>{{ detailData.customer || '-' }}</span>
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

      <div v-if="loadingProcesses" class="oso-empty">
        <UiSpinner />
      </div>
      <template v-else>
        <div v-if="processRows.length === 0" class="oso-empty">
          <FontAwesomeIcon icon="route" aria-hidden="true" />
          <span v-if="isStockinRecord">备货记录无外发工序，仅订单参与外发流程</span>
          <span v-else>该订单尚未配置外发工序</span>
        </div>
        <template v-else>
          <div class="oso-tabs" role="tablist" aria-label="外发工序视图">
            <button
              :class="['oso-tab', { 'oso-tab--active': activeTab === 'progress' }]"
              type="button"
              role="tab"
              :aria-selected="activeTab === 'progress'"
              @click="activeTab = 'progress'"
            >进度</button>
            <button
              :class="['oso-tab', { 'oso-tab--active': activeTab === 'ledger' }]"
              type="button"
              role="tab"
              :aria-selected="activeTab === 'ledger'"
              @click="activeTab = 'ledger'"
            >台账</button>
          </div>
          <OutsourceProcessFlow
            v-if="activeTab === 'progress'"
            :process-groups="processGroups"
            :can-ship="canShip"
            :can-receive="canReceive"
            :status-label="statusLabel"
            :ship-qty-drafts="shipQtyDrafts"
            :receive-qty-drafts="receiveQtyDrafts"
            :set-ship-qty="setShipQty"
            :set-receive-qty="setReceiveQty"
            :remaining-ship-qty="remainingShipQty"
            :remaining-receive-qty="remainingReceiveQty"
          />
          <OutsourceProcessLedger
            v-else
            :total-qty="totalQty"
            :shipped-total="shippedTotal"
            :received-total="receivedTotal"
            :remaining-total="remainingTotal"
            :ship-records="shipRecords"
            :receive-records="receiveRecords"
            :remaining-list="remainingList"
          />
        </template>
      </template>
    </div>
    <template #footer>
      <UiButton variant="outline" @click="detailOpen = false">关闭</UiButton>
      <UiButton
        v-if="canShip"
        variant="primary"
        :disabled="bulkShipping || pendingCount === 0"
        @click="handleBulkShip"
      >
        {{ bulkShipping ? '发货中…' : '一键发货' }}
      </UiButton>
      <UiButton
        v-if="canReceive"
        variant="success"
        :disabled="bulkReceiving || shippedCount === 0"
        @click="handleBulkReceive"
      >
        {{ bulkReceiving ? '收货中…' : '一键收货' }}
      </UiButton>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import { ref, toRef, watch } from 'vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import UiProgressBar from '@/components/ui/UiProgressBar.vue'
import OutsourceProcessFlow from './OutsourceProcessFlow.vue'
import OutsourceProcessLedger from './OutsourceProcessLedger.vue'
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

/** 当前视图：进度 / 台账 */
const activeTab = ref<'progress' | 'ledger'>('progress')

const {
  canShip,
  canReceive,
  loadingProcesses,
  shipQtyDrafts,
  receiveQtyDrafts,
  bulkShipping,
  bulkReceiving,
  pendingCount,
  shippedCount,
  totalQty,
  shippedTotal,
  receivedTotal,
  remainingTotal,
  shipRecords,
  receiveRecords,
  remainingList,
  remainingShipQty,
  remainingReceiveQty,
  setShipQty,
  setReceiveQty,
  isStockinRecord,
  totalProcesses,
  completedProcesses,
  detailProgress,
  detailStatusLabel,
  detailStatusClass,
  processGroups,
  processRows,
  progressVariant,
  loadProcesses,
  loadFlows,
  handleBulkShip,
  handleBulkReceive,
  statusLabel,
} = useOutsourceProcess(detailDataRef, emit)

watch([detailOpen, detailDataRef], ([open, data]) => {
  if (open && data) {
    activeTab.value = 'progress'
    loadProcesses(data.id)
    loadFlows(data.id)
  }
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

.oso-tabs {
  display: inline-flex;
  gap: 2px;
  padding: 3px;
  background: #eef1f5;
  border-radius: 9px;
}
.oso-tab {
  padding: 5px 18px;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--color-text-secondary, #475569);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}
.oso-tab:hover { color: var(--color-text); }
.oso-tab--active {
  background: white;
  color: var(--color-primary-600);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

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
