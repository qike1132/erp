<template>
  <Transition name="drawer">
    <div v-if="open" class="drw-overlay" @click.self="close">
      <div class="drw-panel">
        <div class="drw-header">
          <div class="drw-header-left">
            <h3 class="drw-title">计划详情</h3>
            <span v-if="planData" class="drw-plan-no">{{ planData.plan_no }}</span>
          </div>
          <button class="drw-close" @click="close"><i class="fas fa-times" /></button>
        </div>

        <div v-if="isLoading" class="drw-state"><UiSpinner /> 加载中...</div>
        <div v-else-if="isError" class="drw-state">
          <i class="fas fa-exclamation-circle" style="color:var(--color-danger-500)" /> 加载失败
        </div>
        <template v-else-if="planData">
          <div class="drw-body">
            <div class="drw-section">
              <h4 class="drw-section-title">基本信息</h4>
              <div class="drw-info-grid">
                <div class="drw-info-item">
                  <span class="drw-info-label">客户名称</span>
                  <span class="drw-info-value">{{ planData.customer_name }}</span>
                </div>
                <div class="drw-info-item">
                  <span class="drw-info-label">计划月份</span>
                  <span class="drw-info-value">{{ planData.plan_month }}</span>
                </div>
                <div class="drw-info-item">
                  <span class="drw-info-label">状态</span>
                  <span class="drw-status-badge" :class="planStatusCls(planData.status)">{{ planStatusTxt(planData.status) }}</span>
                </div>
                <div class="drw-info-item">
                  <span class="drw-info-label">创建人</span>
                  <span class="drw-info-value">{{ planData.created_by || '-' }}</span>
                </div>
                <div class="drw-info-item">
                  <span class="drw-info-label">创建时间</span>
                  <span class="drw-info-value">{{ planData.create_time || '-' }}</span>
                </div>
                <div class="drw-info-item">
                  <span class="drw-info-label">备注</span>
                  <span class="drw-info-value">{{ planData.remark || '-' }}</span>
                </div>
              </div>
            </div>

            <div class="drw-section">
              <div class="drw-section-head">
                <h4 class="drw-section-title">计划明细</h4>
                <span class="drw-detail-count">共 {{ details.length }} 条</span>
              </div>
              <div class="drw-details-list">
                <div
                  v-for="d in details"
                  :key="d.id"
                  class="drw-detail-card"
                  :class="{ 'drw-detail-shipped': d.shipment_status === 'completed' }"
                >
                  <div class="drw-detail-top">
                    <span class="drw-detail-product">{{ d.product_name }}</span>
                    <span class="drw-detail-status" :class="detailStatusCls(d.shipment_status)">
                      {{ detailStatusTxt(d.shipment_status) }}
                    </span>
                  </div>
                  <div class="drw-detail-mid">
                    <span class="drw-detail-barcode">{{ d.barcode }}</span>
                    <span class="drw-detail-date">{{ d.plan_date }}</span>
                  </div>
                  <div class="drw-detail-bottom">
                    <div class="drw-detail-qty">
                      <span class="drw-qty-item">
                        <span class="drw-qty-label">计划</span>
                        <span class="drw-qty-val">{{ d.quantity }}</span>
                      </span>
                      <span class="drw-qty-item">
                        <span class="drw-qty-label">已出</span>
                        <span class="drw-qty-val drw-qty-green">{{ d.shipped_qty }}</span>
                      </span>
                      <span class="drw-qty-item">
                        <span class="drw-qty-label">待出</span>
                        <span class="drw-qty-val" :class="d.remaining_qty > 0 ? 'drw-qty-orange' : ''">{{ d.remaining_qty }}</span>
                      </span>
                    </div>
                    <div class="drw-detail-progress">
                      <div class="drw-progress-bar">
                        <div
                          class="drw-progress-fill"
                          :class="d.shipped_qty >= d.quantity ? 'drw-fill-done' : ''"
                          :style="{ width: (d.quantity > 0 ? Math.round((d.shipped_qty / d.quantity) * 100) : 0) + '%' }"
                        />
                      </div>
                      <span class="drw-progress-text">{{ d.quantity > 0 ? Math.round((d.shipped_qty / d.quantity) * 100) : 0 }}%</span>
                    </div>
                  </div>
                  <div v-if="d.inventory_qty !== undefined" class="drw-detail-inventory">
                    <span class="drw-inv-label">库存</span>
                    <span class="drw-inv-val" :class="d.inventory_qty < d.quantity ? 'drw-inv-short' : 'drw-inv-ok'">{{ d.inventory_qty }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </template>
      </div>
    </div>
  </Transition>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { planApi } from '@/api'
import UiSpinner from '@/components/ui/UiSpinner.vue'

const props = defineProps<{
  open: boolean
  planId: number
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  edited: []
}>()

function close() {
  emit('update:open', false)
}

const { data: detailData, isLoading, isError } = useQuery({
  queryKey: ['plan-detail', () => props.planId],
  queryFn: async () => {
    if (!props.planId) return null
    return (await planApi.detail(props.planId)) as any
  },
  enabled: () => props.open && props.planId > 0,
  staleTime: 10_000,
})

const planData = computed(() => detailData.value?.plan ?? null)
const details = computed(() => detailData.value?.details ?? [])

function planStatusCls(s: string) {
  if (s === 'completed') return 'drw-st-completed'
  if (s === 'confirmed') return 'drw-st-confirmed'
  if (s === 'cancelled') return 'drw-st-cancelled'
  return 'drw-st-pending'
}
function planStatusTxt(s: string) {
  if (s === 'completed') return '已完成'
  if (s === 'confirmed') return '已确认'
  if (s === 'cancelled') return '已取消'
  return '待确认'
}
function detailStatusCls(s: string) {
  if (s === 'completed') return 'drw-dst-shipped'
  if (s === 'partial') return 'drw-dst-partial'
  return 'drw-dst-pending'
}
function detailStatusTxt(s: string) {
  if (s === 'completed') return '已出货'
  if (s === 'partial') return '部分出货'
  return '待出货'
}


</script>

<style scoped>
.drw-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: rgba(0, 0, 0, 0.3);
  display: flex;
  justify-content: flex-end;
  backdrop-filter: blur(2px);
}

.drw-panel {
  width: 480px;
  max-width: 90vw;
  height: 100vh;
  background: var(--color-surface-card);
  box-shadow: var(--shadow-xl);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.drw-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 24px;
  border-bottom: 1px solid var(--color-border-light);
  flex-shrink: 0;
}
.drw-header-left {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.drw-title {
  font-size: 1.1rem;
  font-weight: 800;
  color: var(--color-heading);
  margin: 0;
}
.drw-plan-no {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--color-primary-500);
  font-family: var(--font-mono);
}
.drw-close {
  width: 32px; height: 32px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--color-border-light);
  background: var(--color-surface-card);
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  color: var(--color-text-secondary);
  font-size: 0.8rem;
  transition: all 0.2s;
}
.drw-close:hover {
  border-color: var(--color-danger-500);
  color: var(--color-danger-500);
  background: var(--color-danger-50);
}

.drw-state {
  display: flex; align-items: center; justify-content: center;
  padding: 48px 0; color: var(--color-text-muted); gap: 8px;
}

.drw-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.drw-section {}
.drw-section-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.drw-section-title {
  font-size: 0.9rem;
  font-weight: 700;
  color: var(--color-text);
  margin: 0;
  padding-bottom: 4px;
  border-bottom: 2px solid var(--color-primary-100);
  display: inline-block;
}
.drw-detail-count {
  font-size: 0.78rem;
  color: var(--color-text-secondary);
  font-weight: 600;
}

.drw-info-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.drw-info-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.drw-info-label {
  font-size: 0.7rem;
  font-weight: 600;
  color: var(--color-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.drw-info-value {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--color-text);
}

.drw-status-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 6px;
  font-size: 0.72rem;
  font-weight: 600;
  width: fit-content;
}
.drw-st-completed { background: var(--color-success-50); color: var(--color-success-600); }
.drw-st-confirmed { background: var(--color-primary-50); color: var(--color-primary-600); }
.drw-st-cancelled { background: var(--color-danger-50); color: var(--color-danger-600); }
.drw-st-pending { background: var(--color-warning-50); color: var(--color-warning-600); }

.drw-details-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.drw-detail-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: all 0.2s;
}
.drw-detail-card:hover {
  border-color: var(--color-primary-200);
  box-shadow: 0 2px 8px rgba(91, 141, 239, 0.1);
}
.drw-detail-shipped {
  border-left: 3px solid var(--color-success-500);
}

.drw-detail-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.drw-detail-product {
  font-size: 0.85rem;
  font-weight: 700;
  color: var(--color-text);
}
.drw-detail-status {
  font-size: 0.68rem;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
}
.drw-dst-shipped { background: var(--color-success-50); color: var(--color-success-600); }
.drw-dst-partial { background: var(--color-warning-50); color: var(--color-warning-600); }
.drw-dst-pending { background: var(--color-slate-50); color: var(--color-text-secondary); }

.drw-detail-mid {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.drw-detail-barcode {
  font-family: var(--font-mono);
  font-size: 0.72rem;
  color: var(--color-text-muted);
}
.drw-detail-date {
  font-size: 0.75rem;
  color: var(--color-text-secondary);
  font-weight: 600;
}

.drw-detail-bottom {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.drw-detail-qty {
  display: flex;
  gap: 12px;
}
.drw-qty-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
}
.drw-qty-label {
  font-size: 0.6rem;
  font-weight: 600;
  color: var(--color-text-muted);
}
.drw-qty-val {
  font-size: 0.85rem;
  font-weight: 800;
  color: var(--color-text);
}
.drw-qty-green { color: var(--color-success-500); }
.drw-qty-orange { color: var(--color-warning-500); }

.drw-detail-progress {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  max-width: 140px;
}
.drw-progress-bar {
  flex: 1;
  height: 5px;
  border-radius: 3px;
  background: var(--color-border-light);
  overflow: hidden;
}
.drw-progress-fill {
  height: 100%;
  border-radius: 3px;
  background: var(--gradient-primary);
  transition: width 0.4s;
}
.drw-fill-done {
  background: var(--gradient-success);
}
.drw-progress-text {
  font-size: 0.68rem;
  font-weight: 700;
  color: var(--color-text-secondary);
  min-width: 28px;
  text-align: right;
}

.drw-detail-inventory {
  display: flex;
  align-items: center;
  gap: 6px;
  padding-top: 6px;
  border-top: 1px dashed var(--color-border-light);
}
.drw-inv-label {
  font-size: 0.68rem;
  font-weight: 600;
  color: var(--color-text-muted);
}
.drw-inv-val {
  font-size: 0.78rem;
  font-weight: 700;
}
.drw-inv-ok { color: var(--color-success-500); }
.drw-inv-short { color: var(--color-danger-500); }

.drawer-enter-active,
.drawer-leave-active {
  transition: all 0.3s ease;
}
.drawer-enter-from,
.drawer-leave-to {
  opacity: 0;
}
.drawer-enter-from .drw-panel,
.drawer-leave-to .drw-panel {
  transform: translateX(100%);
}
.drawer-enter-active .drw-panel {
  transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
.drawer-leave-active .drw-panel {
  transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

@media (max-width: 640px) {
  .drw-panel { width: 100vw; max-width: 100vw; }
  .drw-info-grid { grid-template-columns: 1fr; }
}
</style>
