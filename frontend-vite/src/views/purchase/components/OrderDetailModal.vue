<template>
  <UiDialog :open="open" @update:open="$emit('close')">
    <template #title>
      <div class="flex items-center gap-2"><i class="fas fa-file-invoice-dollar text-primary-500"  aria-hidden="true" /> 采购订单详情</div>
    </template>

    <div v-if="order" class="space-y-4">
      <div class="grid grid-cols-2 gap-4">
        <div><strong>订单编号：</strong>{{ order.order_no }}</div>
        <div><strong>供应商：</strong>{{ order.supplier_name || '' }}</div>
        <div><strong>客户：</strong>{{ order.customer_name || '-' }}</div>
        <div><strong>下单日期：</strong>{{ order.order_date || '-' }}</div>
        <div><strong>创建时间：</strong>{{ formatDateTime(order.create_time) }}</div>
      </div>
      <div v-if="order.remark"><strong>备注：</strong>{{ order.remark }}</div>
      <h4 class="m-0 mb-2.5 text-sm flex items-center gap-2"><i class="fas fa-list text-primary-500"  aria-hidden="true" /> 物料清单</h4>
      <div class="overflow-x-auto rounded-xl">
        <table class="w-full border-collapse text-[13px] data-table">
          <thead>
            <tr>
              <th>物料编码</th>
              <th>物料名称</th>
              <th>规格</th>
              <th>数量</th>
              <th>单位</th>
              <th>单SKU用量</th>
              <th>分类</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(item, idx) in order.items || []" :key="idx">
              <td>{{ item.material_code || '-' }}</td>
              <td>{{ item.material_name || '-' }}</td>
              <td>{{ item.specification || '-' }}</td>
              <td>{{ item.quantity }}</td>
              <td>{{ item.unit || '-' }}</td>
              <td>{{ item.unit_usage || '-' }}</td>
              <td>{{ item.material_category || '-' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="order.completed_at"><strong>完成时间：</strong>{{ order.completed_at || '-' }}</div>
    </div>

    <template #footer>
      <button
        class="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-lg transition-colors text-text-secondary border border-border bg-transparent hover:text-primary-500 hover:border-primary-500 hover:bg-primary-50"
        @click="$emit('close')"
      >
        关闭
      </button>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import UiDialog from '@/components/ui/UiDialog.vue'
import { formatDateTime } from '@/utils/format'

defineProps<{
  open: boolean
  order: any
}>()

defineEmits<{ close: [] }>()
</script>
