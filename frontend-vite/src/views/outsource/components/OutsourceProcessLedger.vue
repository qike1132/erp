<template>
  <div class="oso-ledger">
    <!-- 汇总条 -->
    <div class="oso-ledger-stats">
      <div class="oso-stat-card">
        <span class="oso-stat-label">订单总数量（件）</span>
        <strong class="oso-stat-val">{{ totalQty }}</strong>
      </div>
      <div class="oso-stat-card oso-stat-card--ship">
        <span class="oso-stat-label">已发货（工序累计）</span>
        <strong class="oso-stat-val">{{ shippedTotal }}</strong>
      </div>
      <div class="oso-stat-card oso-stat-card--recv">
        <span class="oso-stat-label">已收货（工序累计）</span>
        <strong class="oso-stat-val">{{ receivedTotal }}</strong>
      </div>
      <div class="oso-stat-card oso-stat-card--remain">
        <span class="oso-stat-label">未发货（工序累计）</span>
        <strong class="oso-stat-val">{{ remainingTotal }}</strong>
      </div>
    </div>

    <!-- 发货记录 -->
    <div class="oso-ledger-block">
      <h4 class="oso-ledger-title">发货记录</h4>
      <table v-if="shipRecords.length > 0" class="oso-ledger-table">
        <thead>
          <tr><th>时间</th><th>工序</th><th>数量</th><th>操作人</th></tr>
        </thead>
        <tbody>
          <tr v-for="f in shipRecords" :key="'s' + f.id">
            <td>{{ f.create_time || '-' }}</td>
            <td>{{ f.process_type || '-' }}</td>
            <td><strong>{{ f.quantity }}</strong></td>
            <td>{{ f.operator || '—' }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else class="oso-ledger-empty">暂无发货记录</div>
    </div>

    <!-- 收货记录 -->
    <div class="oso-ledger-block">
      <h4 class="oso-ledger-title">收货记录</h4>
      <table v-if="receiveRecords.length > 0" class="oso-ledger-table">
        <thead>
          <tr><th>时间</th><th>工序</th><th>数量</th><th>操作人</th></tr>
        </thead>
        <tbody>
          <tr v-for="f in receiveRecords" :key="'r' + f.id">
            <td>{{ f.create_time || '-' }}</td>
            <td>{{ f.process_type || '-' }}</td>
            <td><strong>{{ f.quantity }}</strong></td>
            <td>{{ f.operator || '—' }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else class="oso-ledger-empty">暂无收货记录</div>
    </div>

    <!-- 未发货清单 -->
    <div class="oso-ledger-block">
      <h4 class="oso-ledger-title">未发货清单</h4>
      <table v-if="remainingList.length > 0" class="oso-ledger-table">
        <thead>
          <tr><th>工序</th><th>目标</th><th>已发</th><th>剩余</th></tr>
        </thead>
        <tbody>
          <tr v-for="(item, i) in remainingList" :key="i">
            <td>{{ item.process_type }}</td>
            <td>{{ item.target }}</td>
            <td>{{ item.shipped }}</td>
            <td><strong class="oso-ledger-remain">{{ item.remaining }}</strong></td>
          </tr>
        </tbody>
      </table>
      <div v-else class="oso-ledger-empty">全部工序已发货</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { OutsourceProcessFlow } from '@/api/outsource'

export interface RemainingLedgerItem {
  process_type: string
  target: number
  shipped: number
  remaining: number
}

defineProps<{
  totalQty: number
  shippedTotal: number
  receivedTotal: number
  remainingTotal: number
  shipRecords: OutsourceProcessFlow[]
  receiveRecords: OutsourceProcessFlow[]
  remainingList: RemainingLedgerItem[]
}>()
</script>

<style scoped>
.oso-ledger {
  display: flex;
  flex-direction: column;
  gap: 14px;
  font-size: 14px;
  color: var(--color-text);
}

.oso-ledger-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}
.oso-stat-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 14px;
  border: 1px solid #e8ecf1;
  border-radius: 12px;
  background: #fcfdfe;
}
.oso-stat-card--ship { background: var(--color-primary-50); border-color: var(--color-primary-100); }
.oso-stat-card--recv { background: var(--color-success-50); border-color: var(--color-success-100); }
.oso-stat-card--remain { background: var(--color-warning-50); border-color: var(--color-warning-100); }
.oso-stat-label { font-size: 11.5px; color: var(--color-text-muted); font-weight: 600; }
.oso-stat-val { font-size: 20px; font-weight: 800; color: var(--color-text); }
.oso-stat-card--ship .oso-stat-val { color: var(--color-primary-600); }
.oso-stat-card--recv .oso-stat-val { color: var(--color-success-700); }
.oso-stat-card--remain .oso-stat-val { color: var(--color-warning-600); }

.oso-ledger-block {
  border: 1px solid #e8ecf1;
  border-radius: 12px;
  background: #fcfdfe;
  overflow: hidden;
}
.oso-ledger-title {
  margin: 0;
  padding: 9px 14px;
  font-size: 12.5px;
  font-weight: 700;
  color: var(--color-text);
  background: #f8fafc;
  border-bottom: 1px solid #e8ecf1;
}
.oso-ledger-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.oso-ledger-table th,
.oso-ledger-table td {
  padding: 8px 12px;
  text-align: left;
  border-bottom: 1px solid #eef1f5;
}
.oso-ledger-table tbody tr:last-child td { border-bottom: none; }
.oso-ledger-table th {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--color-text-muted);
  background: #fafbfc;
  white-space: nowrap;
}
.oso-ledger-remain { color: var(--color-warning-600); }
.oso-ledger-empty {
  padding: 16px;
  text-align: center;
  font-size: 13px;
  color: var(--color-text-muted);
}
</style>
