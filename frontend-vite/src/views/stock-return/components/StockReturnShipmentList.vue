<template>
  <div class="sr-ship-table">
    <table>
      <colgroup>
        <col style="width: 68px" />
        <col style="width: 180px" />
        <col style="width: 158px" />
        <col />
        <col style="width: 80px" />
        <col style="width: 124px" />
      </colgroup>
      <thead>
        <tr>
          <th class="pick-col">选择</th>
          <th>出货单号</th>
          <th>客户</th>
          <th>产品</th>
          <th class="num">可退</th>
          <th>出货日期</th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="loading">
          <td colspan="6" class="empty">加载中…</td>
        </tr>
        <tr v-else-if="shipments.length === 0">
          <td colspan="6" class="empty">没有可退的出货明细（该产品未出货或已退完）</td>
        </tr>
        <tr
          v-for="s in shipments"
          v-else
          :key="s.stockout_id"
          :class="{ picked: pickedId === s.stockout_id }"
          @click="emit('pick', s)"
        >
          <td class="pick-col">
            <input
              type="radio"
              name="shipment-pick"
              :checked="pickedId === s.stockout_id"
              :aria-label="'选择出货单 ' + s.stockout_no"
              @click.stop="emit('pick', s)"
            />
          </td>
          <td class="mono">{{ s.stockout_no }}</td>
          <td class="ellipsis" :title="s.customer || undefined">{{ s.customer || '-' }}</td>
          <td>
            <div class="sr-prod" :title="s.product_name">{{ s.product_name }}</div>
            <div class="sr-prod-sub">出货 {{ s.quantity }} · 已退 {{ s.returned_quantity }}</div>
          </td>
          <td class="num hl">{{ s.available }}</td>
          <td>{{ s.stockout_date }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
/**
 * StockReturnShipmentList.vue — 新增退货弹窗左侧「可退出货明细」表。
 *
 * 从 StockReturnCreateDialog 拆出：该弹窗整体超过 400 行（scripts/check_vue_component_length.py），
 * 把这张表连同它的样式下沉到这里。纯展示 + 单事件，选中态由父级 pickedId 控制。
 */
import type { ShipmentOption } from '@/api/stockReturn'

defineProps<{
  shipments: ShipmentOption[]
  loading: boolean
  pickedId: number | null
}>()

const emit = defineEmits<{ pick: [row: ShipmentOption] }>()
</script>

<style scoped>
.sr-ship-table {
  max-height: 560px;
  overflow-y: auto;
}
.sr-ship-table table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  font-size: 15px;
}
.sr-ship-table thead th {
  position: sticky;
  top: 0;
  z-index: 1;
  padding: 13px 16px;
  background: #fff;
  color: #334155;
  font-weight: 700;
  text-align: left;
  white-space: nowrap;
  border-bottom: 1px solid var(--color-border, #e4e7ed);
}
.sr-ship-table tbody td {
  padding: 13px 16px;
  border-bottom: 1px solid var(--color-border-light, #f0f2f5);
  color: var(--color-text);
  vertical-align: middle;
}
.sr-ship-table tbody tr {
  cursor: pointer;
}
.sr-ship-table tbody tr:hover td {
  background: var(--color-primary-50, #eff5ff);
}
.sr-ship-table tbody tr.picked td {
  background: var(--color-primary-100, #d6e4ff);
}
.sr-ship-table .num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.sr-ship-table .hl {
  color: var(--color-success-700, #2e7d32);
  font-weight: 700;
}
.sr-ship-table .pick-col {
  text-align: center;
}
.sr-ship-table .empty {
  padding: 30px 12px;
  text-align: center;
  color: var(--color-text-muted, #64748b);
}
.mono {
  font-family: var(--font-mono);
  font-weight: 700;
  color: var(--color-primary-700);
}
.ellipsis,
.sr-prod {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.sr-prod {
  font-weight: 600;
  color: var(--color-text);
}
.sr-prod-sub {
  margin-top: 2px;
  font-size: 13px;
  color: var(--color-text-muted, #64748b);
  white-space: nowrap;
}
</style>
