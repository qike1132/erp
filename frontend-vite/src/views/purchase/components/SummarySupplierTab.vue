<template>
  <div
    class="mb-3 p-3 rounded-lg flex justify-between items-center bg-gradient-to-r from-rose/10 to-rose-deep/10"
  >
    <div>
      <div class="font-semibold text-sm mb-1.5">
        <FontAwesomeIcon icon="truck" class="text-rose" aria-hidden="true" /> 供应商采购订单汇总
      </div>
      <div class="text-xs text-text-secondary">
        已选择 <strong class="text-rose">{{ supplierData.order_count || orderCount }}</strong> 个订单，涵盖
        <strong class="text-rose">{{ supplierGroups.length }}</strong> 家供应商，共
        <strong class="text-rose">{{ (supplierData.materials || []).length }}</strong> 种物料
      </div>
    </div>
  </div>

  <div class="max-h-[calc(100vh-320px)] overflow-auto">
    <table class="w-full border-collapse font-[SimSun,_宋体] text-[13px] bg-white">
      <thead>
        <tr class="bg-border-light">
          <th class="w-[12%]">供应商</th>
          <th class="w-[30%]">物料名称</th>
          <th class="w-[28%]">规格型号</th>
          <th class="w-[30%]">数量</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="(sg, sgi) in supplierGroups" :key="sgi">
          <tr v-for="(m, mi) in sg.materials" :key="mi">
            <td v-if="mi === 0" :rowspan="sg.materials.length" class="font-bold">
              {{ sg.supplierName }}
            </td>
            <td>{{ m.material_name }}</td>
            <td>{{ m.specification || '' }}</td>
            <td>{{ formatQty(m.total_quantity) }} {{ m.unit || '' }}</td>
          </tr>
        </template>
        <tr class="bg-border-light font-bold">
          <td class="text-center">合计</td>
          <td />
          <td />
          <td>
            {{ formatQty(supplierGrandTotal) }}
          </td>
        </tr>
      </tbody>
    </table>
  </div>

  <div class="mt-4 pt-3 border-t border-border flex justify-between items-center">
    <div class="flex gap-2">
      <button
        class="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium text-white bg-success-500 rounded-lg border-none transition-colors hover:bg-success-600"
        @click="$emit('exportSupplier')"
      >
        <FontAwesomeIcon icon="file-archive" aria-hidden="true" /> 导出汇总
      </button>
    </div>
    <div class="flex gap-2">
      <button
        class="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium rounded-lg border border-border bg-transparent text-text-secondary hover:text-primary-500 hover:border-primary-500 hover:bg-primary-50 transition-colors"
        @click="$emit('close')"
      >
        关闭
      </button>
      <button
        class="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium text-white bg-primary-500 rounded-lg border-none transition-colors hover:bg-primary-600"
        @click="$emit('printSupplier')"
      >
        <FontAwesomeIcon icon="print" aria-hidden="true" /> 打印预览
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { fmtQty as formatQty } from '@/utils/formatQty'
import type { MaterialItem, SupplierSummaryData } from '../composables/useSummaryModal'

const props = defineProps<{
  supplierData: SupplierSummaryData
  orderCount: number
  supplierGroups: { supplierName: string; materials: MaterialItem[] }[]
}>()

defineEmits<{
  close: []
  exportSupplier: []
  printSupplier: []
}>()

/**
 * 供应商数量合计 = 各物料数量之和。props.supplierGroups 已是「按损耗率派生」的展示副本，
 * 故此处直接累加即与列展示口径一致，无需再放大一次。
 */
const supplierGrandTotal = computed(() => {
  let t = 0
  props.supplierGroups.forEach((g) => g.materials.forEach((m) => (t += parseFloat(String(m.total_quantity)) || 0)))
  return t
})
</script>

<style scoped lang="scss">
/*
  表格外观（边框 / 内边距 / 居中对齐）与工厂页签同源，见 summary-tables.scss。
  本组件自 SummaryModal.vue 抽出后，父组件的 scoped `table th, table td` 规则
  不再穿透到此处，必须显式引入，否则表格会丢失边框（本次补齐）。
*/
@use '@/styles/summary-tables.scss' as *;
</style>
