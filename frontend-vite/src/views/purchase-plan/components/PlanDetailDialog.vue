<template>
  <Transition name="sp-modal">
    <div v-if="open && detail" class="sp-modal-bg" @click.self="close">
      <div class="sp-modal">
        <div class="sp-modal-header">
          <div class="sp-modal-header-info">
            <span class="sp-modal-title">{{ detail.date }} · 周{{ detail._weekday }}</span>
            <div class="sp-modal-tabs">
              <button :class="['sp-modal-tab', { 'sp-modal-tab-active': modalTab === 'plans' }]" @click="modalTab = 'plans'">计划明细</button>
              <button :class="['sp-modal-tab', { 'sp-modal-tab-active': modalTab === 'records' }]" @click="modalTab = 'records'">出货记录</button>
            </div>
          </div>
          <div class="sp-modal-header-progress" v-if="modalTab === 'plans'">
            <div class="sp-modal-progress-bar">
              <div class="sp-modal-progress-fill" :style="{ width: detail._shippedPct + '%' }"></div>
              <span class="sp-modal-progress-text">{{ detail._shippedPct }}%</span>
            </div>
          </div>
          <div class="sp-modal-header-actions">
            <button class="sp-modal-export-btn" @click="exportDayCSV"><FontAwesomeIcon icon="download" aria-hidden="true" /> 导出当日</button>
            <button class="sp-modal-btn sp-modal-btn-close" @click="close" aria-label="关闭"><FontAwesomeIcon icon="times" aria-hidden="true" /></button>
          </div>
        </div>

        <!-- 计划明细 Tab -->
        <div v-if="modalTab === 'plans'" class="sp-modal-body">
          <div class="sp-modal-split">
            <div class="sp-modal-sidebar">
              <VirtualList
                :items="customerList"
                :itemHeight="72"
                :containerHeight="460"
                :itemKey="(c: { name: string }) => c.name"
              >
                <template #default="{ item: entry }">
                  <div
                    class="sp-customer-item"
                    :class="{ 'sp-customer-selected': modalSelCust === entry.name }"
                    @click="modalSelCust = entry.name"
                  >
                    <div class="sp-customer-row">
                      <span class="sp-customer-name">{{ entry.name }}</span>
                      <span class="sp-customer-badge">{{ entry.plans.length }}</span>
                    </div>
                    <div class="sp-customer-summary">
                      <span class="sp-customer-summary-item"><b>{{ entry.plans.reduce((s: number, p: any) => s + Number(p.quantity || 0), 0) }}</b> 计划</span>
                      <span class="sp-customer-summary-item sp-customer-summary-shipped"><b>{{ entry.plans.reduce((s: number, p: any) => s + Number(p.shipped_qty || 0), 0) }}</b> 已出</span>
                      <span class="sp-customer-summary-item sp-customer-summary-pending"><b>{{ entry.plans.reduce((s: number, p: any) => s + Number(p.remaining_qty || 0), 0) }}</b> 待出</span>
                    </div>
                  </div>
                </template>
              </VirtualList>
            </div>
            <div class="sp-modal-main">
              <div v-if="modalSelGroup" class="sp-plan-list-header">
                <span class="sp-plan-list-header-name">产品</span>
                <div class="sp-plan-list-header-qtys">
                  <span>计划</span>
                  <span>已出</span>
                  <span>待出</span>
                </div>
              </div>
              <div v-if="modalSelGroup" class="sp-modal-main-list">
                <VirtualList
                  :items="modalSelGroup"
                  :itemHeight="54"
                  :containerHeight="420"
                  :itemKey="(p: { detail_id: number | string }) => p.detail_id"
                >
                  <template #default="{ item: p }">
                    <div class="sp-plan-item" style="margin-bottom:0;">
                      <div class="sp-plan-left">
                        <span class="sp-plan-name">{{ p.product_name }}</span>
                        <code class="sp-plan-barcode">{{ p.barcode }}</code>
                      </div>
                      <div class="sp-plan-middle">
                        <div class="sp-plan-qtys">
                          <span class="sp-plan-qty-value">{{ p.quantity }}</span>
                          <span class="sp-plan-qty-value sp-qty-green">{{ p.shipped_qty }}</span>
                          <span class="sp-plan-qty-value" :class="p.remaining_qty > 0 ? 'sp-qty-orange' : ''">{{ p.remaining_qty }}</span>
                        </div>
                      </div>
                    </div>
                  </template>
                </VirtualList>
              </div>
              <div v-else class="sp-modal-empty">
                <FontAwesomeIcon icon="hand-pointer" aria-hidden="true" />请从左侧选择客户
              </div>
            </div>
          </div>
        </div>

        <!-- 出货记录 Tab -->
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
import VirtualList from '@/components/ui/VirtualList.vue';
import ShipmentRecordsTab from './ShipmentRecordsTab.vue';
import type { Row } from './types';

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
  modalSelCust.value = d ? Object.keys(d._byCustomer)[0] : '';
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

.sp-modal-sidebar {
  width: 320px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-right: 1px solid var(--color-border-light);
  padding-right: 20px;
}

.sp-customer-item {
  padding: 12px 14px;
  margin-bottom: 8px;
  border: 1px solid var(--color-border-light);
  border-radius: 12px;
  background: white;
  cursor: pointer;
}

.sp-customer-item:hover {
  border-color: var(--color-primary-300);
  background: var(--color-primary-50);
}

.sp-customer-selected {
  border-color: var(--color-primary-500);
  background: var(--color-primary-50);
  box-shadow: 0 2px 8px rgba(91, 141, 239, 0.15);
}

.sp-customer-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.sp-customer-summary {
  display: flex;
  gap: 12px;
  margin-top: 6px;
}

.sp-customer-summary-item {
  font-size: 12px;
  color: var(--color-text-muted);
}

.sp-customer-summary-item b {
  font-weight: 700;
  color: var(--color-text);
  margin-right: 2px;
}

.sp-customer-summary-shipped b {
  color: var(--color-success-600);
}

.sp-customer-summary-pending b {
  color: var(--color-warning-600);
}

.sp-customer-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
}

.sp-customer-badge {
  padding: 3px 8px;
  border-radius: 6px;
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  font-size: 11px;
  font-weight: 600;
}

.sp-modal-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.sp-modal-main-list {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}

.sp-plan-item {
  padding: 8px 16px;
  margin-bottom: 6px;
  border: 1px solid var(--color-border-light);
  border-radius: 10px;
  background: white;
  display: flex;
  align-items: center;
  justify-content: space-between;
  transition: background 0.3s ease, border-color 0.3s ease, box-shadow 0.3s ease;
}

.sp-plan-item:hover {
  border-color: var(--color-primary-500);
  background: var(--color-primary-50);
  box-shadow: 0 2px 8px rgba(91, 141, 239, 0.15);
}

.sp-plan-left {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.sp-plan-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
}

.sp-plan-barcode {
  font-size: 12px;
  color: var(--color-text-muted);
  font-family: var(--font-mono);
}

.sp-plan-middle {
  display: flex;
  align-items: center;
  gap: 20px;
  margin-left: auto;
}

.sp-plan-list-header {
  display: flex;
  align-items: center;
  padding: 0 16px 6px;
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 1px solid var(--color-border-light);
  margin-bottom: 6px;
}

.sp-plan-list-header-qtys {
  display: flex;
  gap: 20px;
  margin-left: auto;
}

.sp-plan-list-header-qtys span {
  min-width: 36px;
  text-align: right;
}

.sp-plan-list-header-name {
  min-width: 0;
}

.sp-plan-qtys {
  display: flex;
  gap: 20px;
}

.sp-plan-qtys .sp-plan-qty-value {
  min-width: 36px;
  text-align: right;
}

.sp-plan-qty-value {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-heading);
}

.sp-qty-green {
  color: var(--color-success-600);
}

.sp-qty-orange {
  color: var(--color-warning-600);
}

.sp-modal-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 60px 20px;
  color: var(--color-text-muted);
  font-size: 14px;
}

.sp-modal-empty i {
  font-size: 28px;
  opacity: 0.5;
}

/* ============ Modal Tabs ============ */
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
