<template>
  <TransitionGroup name="list" tag="div" class="details-list">
    <div
      v-for="d in details"
      :key="d.id"
      class="detail-card"
      :class="{ 'detail-shipped': d.shipment_status === 'completed' }"
    >
      <!-- 产品名 + 状态 -->
      <div class="detail-top">
        <span class="detail-product">{{ d.product_name }}</span>
        <span class="detail-status" :class="detailStatusCls(d.shipment_status)">
          {{ detailStatusTxt(d.shipment_status) }}
        </span>
      </div>

      <!-- 条码 + 日期 -->
      <div class="detail-mid">
        <span class="detail-barcode">{{ d.barcode }}</span>
        <span class="detail-date">{{ d.plan_date }}</span>
      </div>

      <!-- 数量 + 进度条 -->
      <div class="detail-bottom">
        <div class="detail-qty">
          <span class="qty-item">
            <span class="qty-label">计划</span>
            <span class="qty-val">{{ d.quantity }}</span>
          </span>
          <span class="qty-item">
            <span class="qty-label">已出</span>
            <span class="qty-val qty-green">{{ d.shipped_qty }}</span>
          </span>
          <span class="qty-item">
            <span class="qty-label">待出</span>
            <span class="qty-val" :class="{ 'qty-orange': d.remaining_qty > 0 }">
              {{ d.remaining_qty }}
            </span>
          </span>
        </div>
        <div class="detail-progress">
          <div class="progress-bar">
            <div
              class="progress-fill"
              :class="{ 'fill-done': d.shipped_qty >= d.quantity }"
              :style="{ width: (d.quantity > 0 ? Math.round((d.shipped_qty / d.quantity) * 100) : 0) + '%' }"
            />
          </div>
          <span class="progress-text">{{ d.quantity > 0 ? Math.round((d.shipped_qty / d.quantity) * 100) : 0 }}%</span>
        </div>
      </div>

      <!-- 库存提示 -->
      <div v-if="d.inventory_qty !== undefined" class="detail-inventory">
        <span class="inv-label">库存</span>
        <span class="inv-val" :class="d.inventory_qty < d.quantity ? 'inv-short' : 'inv-ok'">
          {{ d.inventory_qty }}
        </span>
      </div>
    </div>
  </TransitionGroup>
</template>

<script setup lang="ts">
interface PlanDetailItem {
  id: number
  shipment_status: string
  product_name: string
  barcode: string
  plan_date: string
  quantity: number
  shipped_qty: number
  remaining_qty: number
  inventory_qty: number
}

defineProps<{
  details: PlanDetailItem[]
}>()

const DETAIL_STATUS_CLASS: Record<string, string> = {
  completed: 'drw-dst-shipped',
  partial: 'drw-dst-partial',
}
const DETAIL_STATUS_TEXT: Record<string, string> = {
  completed: '已出货',
  partial: '部分出货',
}

function detailStatusCls(s: string) { return DETAIL_STATUS_CLASS[s] || 'drw-dst-pending' }
function detailStatusTxt(s: string) { return DETAIL_STATUS_TEXT[s] || '待出货' }
</script>

<style scoped>
.details-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.detail-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.detail-card:hover {
  border-color: var(--color-primary-200);
  box-shadow: 0 2px 8px rgba(91, 141, 239, 0.1);
}
.detail-shipped {
  border-left: 3px solid var(--color-success-500);
}

.detail-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.detail-product {
  font-size: 0.85rem;
  font-weight: 700;
  color: var(--color-text);
}
.detail-status {
  font-size: 0.68rem;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
}
.drw-dst-shipped { background: var(--color-success-50); color: var(--color-success-600); }
.drw-dst-partial { background: var(--color-warning-50); color: var(--color-warning-600); }
.drw-dst-pending { background: var(--color-slate-50); color: var(--color-text-secondary); }

.detail-mid {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.detail-barcode {
  font-family: var(--font-mono);
  font-size: 0.72rem;
  color: var(--color-text-muted);
}
.detail-date {
  font-size: 0.75rem;
  color: var(--color-text-secondary);
  font-weight: 600;
}

.detail-bottom {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.detail-qty {
  display: flex;
  gap: 12px;
}
.qty-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
}
.qty-label {
  font-size: 0.6rem;
  font-weight: 600;
  color: var(--color-text-muted);
}
.qty-val {
  font-size: 0.85rem;
  font-weight: 800;
  color: var(--color-text);
}
.qty-green { color: var(--color-success-500); }
.qty-orange { color: var(--color-warning-500); }

.detail-progress {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  max-width: 140px;
}
.progress-bar {
  flex: 1;
  height: 5px;
  border-radius: 3px;
  background: var(--color-border-light);
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  border-radius: 3px;
  background: var(--gradient-primary);
  transition: width 0.4s;
}
.fill-done { background: var(--gradient-success); }
.progress-text {
  font-size: 0.68rem;
  font-weight: 700;
  color: var(--color-text-secondary);
  min-width: 28px;
  text-align: right;
}

.detail-inventory {
  display: flex;
  align-items: center;
  gap: 6px;
  padding-top: 6px;
  border-top: 1px dashed var(--color-border-light);
}
.inv-label {
  font-size: 0.68rem;
  font-weight: 600;
  color: var(--color-text-muted);
}
.inv-val {
  font-size: 0.78rem;
  font-weight: 700;
}
.inv-ok { color: var(--color-success-500); }
.inv-short { color: var(--color-danger-500); }
</style>