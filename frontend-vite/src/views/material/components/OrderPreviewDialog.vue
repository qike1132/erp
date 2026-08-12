<template>
  <UiDialog :open="open" @update:open="$emit('update:open', $event)" title="采购订单详情" title-icon="" max-width-class="max-w-[720px]">
    <template #title-icon><i class="fas fa-file-invoice" style="color:var(--color-primary-500);"></i></template>
    <div v-if="orderPreview">
      <!-- 来源销售订单 -->
      <div v-if="orderPreview.source_orders && orderPreview.source_orders.length" class="mr-source-section">
        <div class="mr-preview-section-label"><i class="fas fa-link" /> 来源销售订单</div>
        <div v-for="so in orderPreview.source_orders" :key="so.id" class="mr-source-card">
          <div class="mr-det-grid" style="grid-template-columns:1fr 1fr;">
            <div><div class="mr-det-lb">销售订单号</div><div class="mr-det-vl" style="color:var(--color-success-600, #059669);">{{ so.order_no || '-' }}</div></div>
            <div><div class="mr-det-lb">客户</div><div class="mr-det-vl">{{ so.customer_name || '-' }}</div></div>
            <div><div class="mr-det-lb">产品</div><div class="mr-det-vl">{{ so.product_name || '-' }}</div></div>
            <div><div class="mr-det-lb">数量</div><div class="mr-det-vl">{{ so.quantity || '-' }}</div></div>
          </div>
        </div>
      </div>

      <div v-if="orderPreview.remark" style="margin-top:12px;padding:10px 14px;background:var(--color-surface,#f8fafc);border-radius:8px;font-size:13px;color:var(--color-text-secondary);"><b>备注:</b> {{ orderPreview.remark }}</div>
      <div class="mr-preview-section-label"><i class="fas fa-list" /> 物料明细 <span class="mr-preview-count">{{ orderPreview.item_count || (orderPreview.items ? orderPreview.items.length : 0) }} 项</span></div>
      <table v-if="orderPreview.items && orderPreview.items.length" class="mr-item-tbl">
        <thead><tr><th style="width:40%;">物料名称</th><th style="width:30%;">规格</th><th style="width:15%;text-align:right;">数量</th><th style="width:15%;">分类</th></tr></thead>
        <tbody><tr v-for="it in orderPreview.items" :key="it.material_name + it.specification"><td>{{ it.material_name || '-' }}</td><td style="color:var(--color-text-secondary);">{{ it.specification || '-' }}</td><td style="text-align:right;font-weight:500;">{{ it.quantity || 0 }} {{ it.unit || '' }}</td><td>{{ CATEGORY_MAP[it.material_category || ''] || '-' }}</td></tr></tbody>
      </table>
      <div v-else style="text-align:center;padding:20px;color:var(--color-text-muted);">暂无物料明细</div>
    </div>
  </UiDialog>
</template>

<script setup lang="ts">
import UiDialog from '@/components/ui/UiDialog.vue'

interface SourceOrder {
  id?: number
  order_no: string
  customer_name?: string
  product_name?: string
  quantity?: number
}

interface OrderItem {
  material_name: string
  specification?: string
  material_category?: string
  ordered_quantity: number | string
  quantity?: number | string
  unit?: string
}

interface OrderPreview {
  order_no: string
  status: string
  supplier_name: string
  order_date: string
  customer_name?: string
  product_name?: string
  product_quantity?: number
  items: OrderItem[]
  item_count: number
  source_orders?: SourceOrder[]
  remark?: string
}

defineProps<{
  open: boolean
  orderPreview: OrderPreview | null
}>()

defineEmits<{
  'update:open': [value: boolean]
}>()

const CATEGORY_MAP: Record<string, string> = { fabric: '面料', filling: '填充', accessory: '辅料', packaging: '包装' }
</script>

<style scoped>
/* === Detail Grid === */
.mr-det-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; margin-bottom: 20px; }
.mr-det-lb { font-size: 12px; color: var(--color-text-muted); margin-bottom: 6px; }
.mr-det-vl { font-size: 15px; font-weight: 600; color: var(--color-text); }

/* === Preview Dialog Sections === */
.mr-preview-section-label {
  font-size: 13px;
  font-weight: 700;
  color: var(--color-text);
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 12px;
}
.mr-preview-section-label i {
  font-size: 13px;
  color: var(--color-primary-500);
}
.mr-preview-count {
  font-size: 12px;
  font-weight: 400;
  color: var(--color-text-muted);
  margin-left: 4px;
}
.mr-source-section {
  margin-bottom: 16px;
}
.mr-source-card {
  padding: 14px 16px;
  background: linear-gradient(135deg, var(--color-success-50, #ECFDF5), var(--color-surface, #f8fafc));
  border: 1px solid var(--color-success-200, #A7F3D0);
  border-radius: 12px;
  margin-bottom: 8px;
}
.mr-source-card:last-child {
  margin-bottom: 0;
}

.mr-item-tbl { width: 100%; border-collapse: collapse; }
.mr-item-tbl th { background: var(--color-surface, #f8fafc); padding: 10px 12px; font-size: 12px; text-align: left; }
.mr-item-tbl td { padding: 10px 12px; border-bottom: 1px solid var(--color-border-light, #e2e8f0); font-size: 13px; }
</style>
