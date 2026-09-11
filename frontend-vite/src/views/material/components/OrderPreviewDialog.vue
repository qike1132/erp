<template>
  <UiDialog :open="open" @update:open="$emit('update:open', $event)" title="采购订单详情" title-icon="" max-width-class="max-w-[720px]">
    <template #title-icon><FontAwesomeIcon :icon="faFileInvoice" style="color:var(--color-primary-500);" /></template>
    <div v-if="orderPreview">
      <!-- 来源销售订单 -->
      <div v-if="orderPreview.source_orders && orderPreview.source_orders.length" class="mr-source-section">
        <div class="mr-preview-section-label"><FontAwesomeIcon :icon="faLink" /> 来源销售订单</div>
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
      <div class="mr-preview-section-label"><FontAwesomeIcon :icon="faList" /> 物料明细 <span class="mr-preview-count">{{ orderPreview.item_count || (orderPreview.items ? orderPreview.items.length : 0) }} 项</span></div>
      <table v-if="orderPreview.items && orderPreview.items.length" class="mr-item-tbl">
        <thead><tr><th style="width:40%;">物料名称</th><th style="width:30%;">规格</th><th style="width:15%;text-align:right;">数量</th><th style="width:15%;">分类</th></tr></thead>
        <tbody><tr v-for="it in orderPreview.items" :key="it.material_name + it.specification"><td>{{ it.material_name || '-' }}</td><td style="color:var(--color-text-secondary);">{{ it.specification || '-' }}</td><td style="text-align:right;font-weight:500;">{{ it.quantity || 0 }} {{ it.unit || '' }}</td><td>{{ CATEGORY_MAP[it.material_category || ''] || '-' }}</td></tr></tbody>
      </table>
      <div v-else style="text-align:center;padding:20px;color:var(--color-text-muted);">暂无物料明细</div>
    </div>
  </UiDialog>
</template>

<script setup lang="ts">
// 图标走全局 tree-shaking 管线（src/icons.ts library.add + FontAwesomeIcon SVG 组件），
// 不再引入 @fortawesome/fontawesome-free 全量 CSS
import { faFileInvoice, faLink, faList } from '@fortawesome/free-solid-svg-icons'
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

<style scoped lang="scss">
@use '../material-dialogs.scss' as *;
</style>
