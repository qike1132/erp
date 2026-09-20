<template>
  <!-- 工序紧凑分组表格：每 SKU 一组表头行 + 工序行（工序/发货数量/收货数量/状态） -->
  <div v-for="group in processGroups" :key="String(group.itemId)" class="oso-proc-group">
    <div class="oso-proc-group-head">
      <span class="oso-proc-sku">{{ group.skuName || 'SKU' }}</span>
      <span class="oso-proc-qty">订单数量 {{ group.skuQty }}</span>
      <span class="oso-proc-count">{{ group.processes.length }} 道工序</span>
    </div>
    <table class="oso-proc-table">
      <thead>
        <tr>
          <th class="oso-col-proc">工序</th>
          <th class="oso-col-qty">已发数量</th>
          <th class="oso-col-time">发货时间</th>
          <th class="oso-col-qty">剩余未发</th>
          <th class="oso-col-qty">收货数量</th>
          <th class="oso-col-time">湖北收货时间</th>
          <th class="oso-col-status">状态</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(p, idx) in group.processes" :key="p.id" :class="`oso-proc-row--${p.status}`">
          <td class="oso-col-proc">
            <span class="oso-proc-seq">{{ idx + 1 }}</span>
            <span class="oso-proc-name">{{ p.process_type }}</span>
          </td>
          <td class="oso-col-qty">
            <template v-if="canShip && remainingShipQty(p) > 0 && (p.received_quantity || 0) === 0">
              <input
                class="oso-qty-input"
                type="number"
                min="1"
                placeholder="本批发货"
                :value="shipQtyDrafts[p.id] ?? remainingShipQty(p)"
                :title="`本次发货数量（剩余 ${remainingShipQty(p)}）`"
                @input="setShipQty(p.id, ($event.target as HTMLInputElement).value)"
              />
            </template>
            <template v-else>
              <span class="oso-qty-val">{{ p.shipped_quantity || '-' }}</span>
            </template>
          </td>
          <td class="oso-col-time">
            <span class="oso-time-val">{{ p.actual_start_time || '-' }}</span>
          </td>
          <td class="oso-col-qty">
            <strong class="oso-remain">{{ remainingShipQty(p) }}</strong>
          </td>
          <td class="oso-col-qty">
            <template v-if="canReceive && remainingReceiveQty(p) > 0">
              <input
                class="oso-qty-input"
                type="number"
                min="1"
                placeholder="本批收货"
                :value="receiveQtyDrafts[p.id] ?? remainingReceiveQty(p)"
                :title="`本次收货数量（剩余 ${remainingReceiveQty(p)}）`"
                @input="setReceiveQty(p.id, ($event.target as HTMLInputElement).value)"
              />
            </template>
            <template v-else>
              <span class="oso-qty-val">{{ p.received_quantity || '-' }}</span>
            </template>
          </td>
          <td class="oso-col-time">
            <span class="oso-time-val">{{ p.actual_end_time || '-' }}</span>
          </td>
          <td class="oso-col-status">
            <span :class="['oso-status-badge', `oso-status-${p.status}`]">{{ statusLabel(p.status) }}</span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
import type { OrderOutsourceProcess } from '@/api/outsource'
import type { ProcessGroup } from '@/views/outsource/composables/useOutsourceProcess'

defineProps<{
  processGroups: ProcessGroup[]
  canShip: boolean
  canReceive: boolean
  statusLabel: (status: string) => string
  shipQtyDrafts: Record<number, string>
  receiveQtyDrafts: Record<number, string>
  setShipQty: (id: number, value: string) => void
  setReceiveQty: (id: number, value: string) => void
  remainingShipQty: (p: OrderOutsourceProcess) => number
  remainingReceiveQty: (p: OrderOutsourceProcess) => number
}>()
</script>

<style scoped>
.oso-proc-group {
  border: 1px solid #e8ecf1;
  border-radius: 12px;
  background: #fcfdfe;
  overflow: hidden;
}
.oso-proc-group + .oso-proc-group {
  margin-top: 12px;
}
.oso-proc-group-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 14px;
  background: #f8fafc;
  border-bottom: 1px solid #e8ecf1;
}
.oso-proc-sku { font-weight: 700; font-size: 13.5px; color: var(--color-text); }
.oso-proc-qty { font-size: 12px; color: var(--color-text-muted); }
.oso-proc-count { margin-left: auto; font-size: 11.5px; color: var(--color-text-muted); }

.oso-proc-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.oso-proc-table th,
.oso-proc-table td {
  padding: 8px 12px;
  text-align: left;
  border-bottom: 1px solid #eef1f5;
}
.oso-proc-table tbody tr:last-child td { border-bottom: none; }
.oso-proc-table th {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--color-text-muted);
  background: #fafbfc;
  white-space: nowrap;
}
.oso-proc-table tbody tr:hover { background: #fafbfc; }

.oso-col-proc { width: 22%; }
.oso-col-qty { width: 11%; }
.oso-col-time { width: 15%; }
.oso-col-status { width: 11%; }
.oso-time-val { font-size: 12px; color: var(--color-text-secondary); white-space: nowrap; }
.oso-remain { color: var(--color-warning-600); font-weight: 700; }

.oso-proc-seq {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 20px;
  margin-right: 8px;
  padding: 0 4px;
  border-radius: 6px;
  background: #f1f5f9;
  color: var(--color-text-muted);
  font-size: 11.5px;
  font-weight: 700;
}
.oso-proc-row--shipped .oso-proc-seq { background: var(--color-primary-50); color: var(--color-primary-600); }
.oso-proc-row--received .oso-proc-seq { background: var(--color-success-100); color: var(--color-success-700); }
.oso-proc-name {
  font-weight: 600;
  color: var(--color-text);
}
.oso-proc-cum {
  margin-left: 8px;
  font-size: 11px;
  color: var(--color-text-muted);
}

.oso-qty-val { font-weight: 700; color: var(--color-text); }
.oso-qty-input {
  width: 88px;
  padding: 4px 8px;
  font-size: 12px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background: white;
  color: var(--color-text);
}
.oso-qty-input:focus { outline: 2px solid var(--color-primary-500); outline-offset: 1px; border-color: var(--color-primary-400); }

.oso-status-badge {
  display: inline-block;
  padding: 2px 9px;
  border-radius: 7px;
  font-size: 11.5px;
  font-weight: 600;
  white-space: nowrap;
}
.oso-status-pending { background: var(--color-warning-50); color: var(--color-warning-600); }
.oso-status-shipped { background: var(--color-primary-50); color: var(--color-primary-600); }
.oso-status-received { background: var(--color-success-50); color: var(--color-success-700); }
</style>
