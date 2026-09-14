<template>
  <!-- 订单详情弹窗 -->
  <UiDialog v-model:open="detailOpen" title="订单详情" max-width-class="max-w-[900px]">
    <div v-if="detailData" class="bo-detail-body">
      <!-- 基础信息行：一行展示 -->
      <div class="bo-detail-meta-row">
        <span class="bo-detail-meta-item"><span class="bo-detail-meta-label">下单时间</span> {{ detailData.order_date || '-' }}</span>
        <span class="bo-detail-meta-sep">|</span>
        <span class="bo-detail-meta-item"><span class="bo-detail-meta-label">客户</span> {{ detailData.customer || '-' }}</span>
        <span class="bo-detail-meta-sep">|</span>
        <span class="bo-detail-meta-item"><span class="bo-detail-meta-label">工厂</span> {{ detailData.factories?.join(', ') || '湖北' }}</span>
        <span class="bo-detail-meta-sep">|</span>
        <span class="bo-detail-meta-item"><span class="bo-detail-meta-label">总数量</span> <strong class="bo-detail-meta-num">{{ detailTotalQuantity }}</strong></span>
      </div>

      <!-- 确认信息：订单与备货均参与确认流程 -->
      <div class="bo-detail-meta-row">
        <span class="bo-detail-meta-item">
          <span class="bo-detail-meta-label">确认状态</span>
          <span v-if="detailData.confirmed" class="bo-confirm-badge bo-confirm-badge--done">已确认</span>
          <span v-else class="bo-confirm-badge bo-confirm-badge--pending">未确认</span>
        </span>
        <span class="bo-detail-meta-sep">|</span>
        <span class="bo-detail-meta-item"><span class="bo-detail-meta-label">确认时间</span> {{ detailData.confirmed_at || '-' }}</span>
        <span class="bo-detail-meta-sep">|</span>
        <span class="bo-detail-meta-item"><span class="bo-detail-meta-label">确认人</span> {{ detailData.confirmed_by || '-' }}</span>
      </div>

      <!-- SKU 明细表格 -->
      <div class="bo-detail-table-wrap">
        <table class="bo-detail-table">
          <thead>
            <tr>
              <th style="width:38%">产品名称</th>
              <th style="width:18%">产品条码</th>
              <th style="width:10%;text-align:right">数量</th>
              <th style="width:34%">备注</th>
            </tr>
          </thead>
          <tbody>
            <template v-if="(detailData.items || []).length > 0">
              <tr v-for="sku in detailData.items" :key="sku.id">
                <td class="bo-detail-td-name">{{ sku.product_name || detailData.product_name || '-' }}</td>
                <td class="bo-detail-td-barcode">{{ sku.product_barcode || detailData.barcode || '-' }}</td>
                <td class="bo-detail-td-qty"><strong>{{ sku.quantity ?? detailData.quantity }}</strong></td>
                <td class="bo-detail-td-note" :title="(sku.note || detailData.note || '')">{{ sku.note || detailData.note || '-' }}</td>
              </tr>
            </template>
            <template v-else>
              <tr v-if="detailData.product_name">
                <td class="bo-detail-td-name">{{ detailData.product_name }}</td>
                <td class="bo-detail-td-barcode">{{ detailData.barcode || '-' }}</td>
                <td class="bo-detail-td-qty"><strong>{{ detailData.quantity }}</strong></td>
                <td class="bo-detail-td-note" :title="(detailData.note || '')">{{ detailData.note || '-' }}</td>
              </tr>
              <tr v-else>
                <td colspan="4" class="bo-detail-td-empty">暂无 SKU 明细</td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </div>
    <template #footer>
      <UiButton variant="outline" @click="detailOpen = false">关闭</UiButton>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
/**
 * BeileOrderDetailDialog.vue — 湖北订单详情弹窗
 *
 * 从 BeileOrderTab.vue 拆出：基础信息 + 确认信息 + SKU 明细表格。
 */
import { computed } from 'vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiButton from '@/components/ui/UiButton.vue'
import type { BeileOrderRow } from '@/views/beile-order/composables/useBeileOrders'

const props = defineProps<{
  /** 当前查看的订单行 */
  detailData: BeileOrderRow | null
}>()

/** 弹窗开关（父组件 v-model:open） */
const detailOpen = defineModel<boolean>('open', { default: false })

/** 详情总数量：优先按 SKU 明细汇总，无明细时用订单总量 */
const detailTotalQuantity = computed(() => {
  if (!props.detailData) return 0
  const items = props.detailData.items || []
  if (items.length === 0) return props.detailData.quantity || 0
  return items.reduce((sum, s) => sum + (s.quantity || 0), 0)
})
</script>

<style scoped>
/* ===== 订单详情弹窗 ===== */
.bo-detail-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
  font-size: 14px;
  color: var(--color-text);
}

/* 基础信息行：一行内联展示 */
.bo-detail-meta-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 12px;
  padding: 10px 14px;
  background: #f8fafc;
  border-radius: 8px;
  font-size: 13px;
  color: var(--color-text);
}
.bo-detail-meta-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
}
.bo-detail-meta-label {
  color: var(--color-text-muted, #64748b);
  font-size: 12px;
}
.bo-detail-meta-sep {
  color: #cbd5e1;
  user-select: none;
}
.bo-detail-meta-num {
  color: var(--color-primary-700, #2d5ab8);
}

/* 确认状态徽章（确认信息行用） */
.bo-confirm-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 3px 10px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}
.bo-confirm-badge--pending {
  background: var(--color-warning-50);
  color: var(--color-warning-600);
}
.bo-confirm-badge--done {
  background: var(--color-success-50);
  color: var(--color-success-700);
}

/* SKU 明细表格 */
.bo-detail-table-wrap {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  overflow: hidden;
}
.bo-detail-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.bo-detail-table thead th {
  padding: 10px 12px;
  font-weight: 600;
  font-size: 12px;
  color: #64748b;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  white-space: nowrap;
  text-align: left;
}
.bo-detail-table tbody td {
  padding: 10px 12px;
  border-bottom: 1px solid #f1f5f9;
  vertical-align: middle;
}
.bo-detail-table tbody tr:last-child td {
  border-bottom: none;
}
.bo-detail-td-name {
  font-weight: 500;
  white-space: nowrap;
}
.bo-detail-td-qty {
  text-align: right;
  font-weight: 600;
  color: var(--color-primary-700, #2d5ab8);
}
.bo-detail-td-note {
  color: var(--color-text-secondary, #475569);
  font-size: 12px;
  word-break: break-word;
}
.bo-detail-td-empty {
  text-align: center;
  color: #94a3b8;
  padding: 28px 12px !important;
}

/* 响应式 */
@media (max-width: 640px) {
  .bo-detail-meta-row { flex-direction: column; align-items: flex-start; }
  .bo-detail-meta-sep { display: none; }
}
</style>
