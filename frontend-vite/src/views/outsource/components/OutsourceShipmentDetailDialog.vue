<template>
  <UiDialog v-model:open="open" title="发货单明细" max-width-class="max-w-[900px]">
    <div class="osdd-body">
      <div v-if="loading" class="osdd-empty"><UiSpinner /></div>
      <div v-else-if="!shipment" class="osdd-empty">
        <FontAwesomeIcon icon="truck-fast" aria-hidden="true" />
        <span>发货单不存在</span>
      </div>
      <template v-else>
        <!-- 单据信息 -->
        <div class="osdd-meta">
          <div class="osdd-meta-row">
            <span class="osdd-meta-label">发货单号</span>
            <span class="osdd-mono">{{ shipment.shipment_no }}</span>
            <span :class="['osdd-status-badge', statusClass(shipment.status)]">{{ statusLabel(shipment.status) }}</span>
          </div>
          <div class="osdd-meta-grid">
            <div class="osdd-meta-item"><span class="osdd-meta-label">客户</span><span>{{ shipment.customer || '-' }}</span></div>
            <div class="osdd-meta-item"><span class="osdd-meta-label">发货人</span><span>{{ shipment.shipped_by || '-' }}</span></div>
            <div class="osdd-meta-item"><span class="osdd-meta-label">发货时间</span><span>{{ shipment.shipped_at || '-' }}</span></div>
            <div class="osdd-meta-item"><span class="osdd-meta-label">收货人</span><span>{{ shipment.received_by || '-' }}</span></div>
            <div class="osdd-meta-item"><span class="osdd-meta-label">收货时间</span><span>{{ shipment.received_at || '-' }}</span></div>
          </div>
        </div>

        <!-- 明细表：SKU + 工序 + 发货/收货数量 -->
        <div class="osdd-table-wrap">
          <table class="osdd-table">
            <thead>
              <tr>
                <th style="width: 60px;">#</th>
                <th>SKU</th>
                <th style="width: 120px;">工序</th>
                <th style="width: 110px;">订单总数</th>
                <th style="width: 100px;">发货数量</th>
                <th style="width: 100px;">收货数量</th>
                <th style="width: 100px;">未收货</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(it, idx) in items" :key="it.id">
                <td>{{ idx + 1 }}</td>
                <td class="osdd-td-left">{{ it.product_name || '-' }}</td>
                <td><span class="osdd-proc">{{ it.process_type }}</span></td>
                <td class="osdd-num osdd-order-qty">{{ it.order_qty != null ? it.order_qty.toLocaleString() : '-' }}</td>
                <td class="osdd-num">{{ it.shipped_quantity.toLocaleString() }}</td>
                <td class="osdd-num osdd-received">{{ it.received_quantity.toLocaleString() }}</td>
                <td class="osdd-num" :class="{ 'osdd-pending': pendingOf(it) > 0 }">{{ pendingOf(it).toLocaleString() }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="osdd-foot">
          <span>共 <strong>{{ items.length }}</strong> 道工序 · 发货 <strong>{{ shipment.total_shipped.toLocaleString() }}</strong> 件</span>
        </div>
      </template>
    </div>
    <template #footer>
      <UiButton variant="outline" @click="open = false">关闭</UiButton>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
/**
 * OutsourceShipmentDetailDialog.vue — 发货单明细弹窗
 *
 * 表格展示每个 SKU 及其工序的发货数量、收货数量、未收货数量与订单状态。
 */
import { computed, ref, watch } from 'vue'
import { outsourceApi, type Shipment } from '@/api/outsource'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import { toast } from '@/composables/useToast'

const open = defineModel<boolean>('open', { default: false })
const props = defineProps<{ shipmentId: number | null }>()

const shipment = ref<Shipment | null>(null)
const loading = ref(false)

watch(open, (v) => { if (v) load() })

async function load() {
  if (props.shipmentId == null) return
  loading.value = true
  shipment.value = null
  try {
    shipment.value = await outsourceApi.shipmentDetail(props.shipmentId)
  } catch {
    toast.error('加载发货单明细失败')
  } finally {
    loading.value = false
  }
}

const items = computed(() => shipment.value?.items ?? [])

function pendingOf(it: { shipped_quantity: number; received_quantity: number }): number {
  return Math.max(0, it.shipped_quantity - it.received_quantity)
}

function statusLabel(status: string): string {
  return status === 'received' ? '已完成' : '待收货'
}
function statusClass(status: string): string {
  return status === 'received' ? 'osdd-status-received' : 'osdd-status-shipped'
}
</script>

<style scoped>
.osdd-body { display: flex; flex-direction: column; gap: 12px; min-height: 0; }
.osdd-meta { display: flex; flex-direction: column; gap: 8px; padding: 12px 14px; background: var(--color-surface, #f8fafc); border: 1px solid #e8ecf1; border-radius: 10px; }
.osdd-meta-row { display: flex; align-items: center; gap: 10px; }
.osdd-meta-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px 16px; font-size: 13px; }
.osdd-meta-item { display: flex; gap: 8px; }
.osdd-meta-label { color: var(--color-text-muted, #64748b); font-weight: 600; flex-shrink: 0; }
.osdd-mono { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 13px; font-weight: 700; }
.osdd-status-badge { display: inline-block; padding: 2px 9px; border-radius: 7px; font-size: 11.5px; font-weight: 600; }
.osdd-status-shipped { background: var(--color-warning-50); color: var(--color-warning-600); }
.osdd-status-received { background: var(--color-success-50); color: var(--color-success-700); }

.osdd-table-wrap { max-height: 400px; overflow-y: auto; border: 1px solid #e8ecf1; border-radius: 10px; }
.osdd-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.osdd-table thead { position: sticky; top: 0; background: #f8fafc; z-index: 1; }
.osdd-table th {
  padding: 9px 12px; font-size: 11.5px; font-weight: 600; color: var(--color-text-muted, #64748b);
  text-align: center; border-bottom: 1px solid #e8ecf1; white-space: nowrap;
}
.osdd-table td { padding: 8px 12px; border-bottom: 1px solid #eef2f7; text-align: center; vertical-align: middle; }
.osdd-table tbody tr:last-child td { border-bottom: none; }
.osdd-td-left { text-align: left !important; }
.osdd-proc {
  display: inline-block; font-size: 12px; font-weight: 600; color: var(--color-primary-700, #1d4ed8);
  background: var(--color-primary-50, #eff6ff); border: 1px solid var(--color-primary-200, #bfdbfe);
  border-radius: 6px; padding: 1px 8px;
}
.osdd-num { font-variant-numeric: tabular-nums; }
/* 订单总数：作为对比基准，弱化于实际发货/收货数字 */
.osdd-order-qty { color: var(--color-text-muted, #64748b); }
.osdd-received { color: var(--color-success-600, #16a34a); font-weight: 600; }
.osdd-pending { color: var(--color-warning-600, #d97706); font-weight: 700; }
.osdd-foot { display: flex; justify-content: flex-end; font-size: 13px; color: var(--color-text-secondary, #475569); }
.osdd-foot strong { color: var(--color-primary-600, #2563eb); }
.osdd-empty { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 40px 20px; color: var(--color-text-muted, #64748b); }
.osdd-empty span { font-size: 14px; }
</style>
