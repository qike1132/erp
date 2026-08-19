<template>
  <Transition name="sp-modal">
    <div v-if="open && detail" class="sp-modal-bg" @click.self="close">
      <div class="sp-modal">
        <div class="sp-modal-header">
          <div class="sp-modal-header-info">
            <span class="sp-modal-title">{{ detail.date }} · 周{{ detail._weekday }}</span>
            <div class="sp-modal-tabs">
              <button :class="['sp-modal-tab', { 'sp-modal-tab-active': modalTab === 'plans' }]" @click="modalTab = 'plans'" aria-label="计划明细">计划明细</button>
              <button :class="['sp-modal-tab', { 'sp-modal-tab-active': modalTab === 'records' }]" @click="modalTab = 'records'" aria-label="出货记录">出货记录</button>
            </div>
          </div>
          <div class="sp-modal-header-progress" v-if="modalTab === 'plans'">
            <div class="sp-modal-progress-bar">
              <div class="sp-modal-progress-fill" :style="{ width: detail._shippedPct + '%' }"></div>
              <span class="sp-modal-progress-text">{{ detail._shippedPct }}%</span>
            </div>
          </div>
          <div class="sp-modal-header-actions">
            <button class="sp-modal-export-btn" @click="exportDayCSV" aria-label="导出当日"><FontAwesomeIcon icon="download" aria-hidden="true" /> 导出当日</button>
            <button class="sp-modal-btn sp-modal-btn-close" @click="close" aria-label="关闭"><FontAwesomeIcon icon="times" aria-hidden="true" /></button>
          </div>
        </div>

        <div v-if="modalTab === 'plans'" class="sp-modal-body">
          <div class="sp-modal-split">
            <PlanDialogCustomerList
              :customer-list="customerList"
              :selected="modalSelCust"
              @select="modalSelCust = $event"
            />
            <PlanDialogPlanList :items="modalSelGroup" />
          </div>
        </div>

        <div v-else class="sp-modal-body">
          <ShipmentRecordsTab :date="detail.date" :plans="detail.plans" />
        </div>

      </div>
    </div>
  </Transition>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import { showToast } from '@/composables/useToast';
import { downloadCsv } from '@/utils/csv';
import ShipmentRecordsTab from './ShipmentRecordsTab.vue';
import PlanDialogCustomerList from './PlanDialogCustomerList.vue';
import PlanDialogPlanList from './PlanDialogPlanList.vue';
import type { Row, Plan } from './types';

const props = defineProps<{
  open: boolean;
  detail: Row | null;
}>();

const emit = defineEmits<{
  'update:open': [value: boolean];
}>();

const modalTab = ref<'plans' | 'records'>('plans');
const modalSelCust = ref('');

watch(() => props.detail, (d) => {
  modalSelCust.value = d ? (Object.keys(d._byCustomer)[0] ?? '') : '';
  modalTab.value = 'plans';
});

const customerList = computed(() => {
  if (!props.detail) return [];
  return Object.entries(props.detail._byCustomer).map(([name, plans]) => ({ name, plans }));
});

const modalSelGroup = computed(() => {
  if (!modalSelCust.value || !props.detail) return null;
  return props.detail._byCustomer[modalSelCust.value] ?? null;
});

function getShipmentStatus(quantity: number, shippedQty: number): string {
  if (shippedQty >= quantity) return 'completed';
  if (shippedQty > 0) return 'partial';
  return 'pending';
}

function exportDayCSV() {
  if (!props.detail) return;
  const r = props.detail;
  const h = '客户,产品,条码,数量,已出,待出,状态';
  const ls = [h];
  for (const p of r.plans) {
    const st = getShipmentStatus(p.quantity, p.shipped_qty);
    ls.push([p.customer_name, p.product_name, p.barcode, p.quantity, p.shipped_qty, p.remaining_qty, st === 'completed' ? '已出货' : st === 'partial' ? '部分出货' : '待出货'].join(','));
  }
  downloadCsv(ls, `出货计划_${r.date}_详情.csv`);
  showToast('导出成功', 'success');
}

function close() {
  emit('update:open', false);
}
</script>

<style scoped>
.sp-modal-bg {
  position: fixed;
  inset: 0;
  z-index: 900;
  background: rgba(0,0,0,0.4);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.sp-modal {
  width: 1200px;
  max-width: 96vw;
  height: 85vh;
  max-height: 94vh;
  background: white;
  border-radius: 18px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.08), 0 24px 80px rgba(0,0,0,0.12);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.sp-modal-header {
  display: flex;
  align-items: center;
  padding: 16px 24px;
  border-bottom: 1px solid var(--color-border-light);
  flex-shrink: 0;
  gap: 16px;
}

.sp-modal-header-info {
  display: flex;
  align-items: center;
  gap: 10px;
}

.sp-modal-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--color-heading);
}

.sp-modal-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.sp-modal-btn {
  width: 36px;
  height: 36px;
  border-radius: 9px;
  border: 1px solid var(--color-border-light);
  background: white;
  color: var(--color-text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: border-color 0.3s ease, color 0.3s ease, background 0.3s ease;
}

.sp-modal-btn:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-500);
  background: var(--color-primary-50);
}

.sp-modal-export-btn {
  height: 36px;
  padding: 0 14px;
  border-radius: 9px;
  border: 1px solid var(--color-border-light);
  background: white;
  color: var(--color-text-secondary);
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  transition: border-color 0.3s ease, color 0.3s ease, background 0.3s ease;
}

.sp-modal-export-btn:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-500);
  background: var(--color-primary-50);
}

.sp-modal-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  padding: 20px 24px;
}

.sp-modal-header-progress {
  flex: 1;
  flex-shrink: 0;
}

.sp-modal-progress-bar {
  position: relative;
  height: 36px;
  border-radius: 9px;
  border: 1px solid var(--color-border-light);
  background: white;
  overflow: hidden;
}

.sp-modal-progress-fill {
  height: 100%;
  background: linear-gradient(135deg, var(--color-success-400), var(--color-success-600));
  border-radius: var(--radius-input);
  transition: width 0.6s cubic-bezier(0.4, 0, 0.2, 1);
}

.sp-modal-progress-text {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  color: var(--color-heading);
}

.sp-modal-split {
  display: flex;
  flex: 1;
  min-height: 0;
  gap: 20px;
}

.sp-modal-tabs {
  display: inline-flex;
  gap: 2px;
  padding: 3px;
  border-radius: 8px;
  background: var(--color-surface, #f8fafc);
  border: 1px solid var(--color-border-light, #e2e8f0);
  margin-top: 8px;
}
.sp-modal-tab {
  padding: 5px 14px;
  border: none;
  border-radius: 6px;
  background: transparent;
  font-size: 12px;
  font-weight: 700;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: background 0.2s, color 0.2s;
  font-family: inherit;
}
.sp-modal-tab:hover { background: var(--color-primary-50); color: var(--color-primary-600); }
.sp-modal-tab-active { background: white; color: var(--color-primary-700); box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
</style>
