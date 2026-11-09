<template>
  <!-- 整页视图内的页签：自身也是 flex 列（父级 .sm-body 是 flex），
       中段表格是唯一滚动区（flex:1 + min-h:0 撑满剩余高度），顶部概要行常驻；
       底部操作条已删（导出/打印/返回都在头部）。 -->
  <div class="sms-tab">
    <!-- 概要行（2026-10-31 用户嫌空白多）：删渐变底色大条，压成单行紧凑文字。 -->
    <div class="sms-toolbar flex-shrink-0">
      <div class="text-[14px] text-text-secondary">
        已选择 <strong class="text-rose">{{ supplierData.order_count || orderCount }}</strong> 个订单，涵盖
        <strong class="text-rose">{{ supplierGroups.length }}</strong> 家供应商，共
        <strong class="text-rose">{{ (supplierData.materials || []).length }}</strong> 种物料
      </div>
    </div>

    <div class="sms-scroll">
      <!-- 2026-10-31 用户反馈：不铺满、但也不要太小——取 72% 宽度居中，
           比例适中；窄屏由 min-w 兜底（容器内可横向滚动）。 -->
      <table class="w-[72%] min-w-[860px] mx-auto border-collapse font-sans text-[14px] bg-white">
        <thead>
          <tr class="bg-border-light">
            <th>供应商</th>
            <th class="w-[240px]">物料名称</th>
            <th>规格型号</th>
            <th>数量</th>
            <th>单位</th>
            <th class="w-[200px]">来源订单</th>
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
              <td>{{ qtyDisplayText(m.total_quantity) }}</td>
              <td>{{ m.unit || '' }}</td>
              <!-- 来源订单：逐单平铺「采购单号 + 该单数量」，不折叠 -->
              <td class="src-orders">
                <template v-if="orderLines(m).length">
                  <div v-for="o in orderLines(m)" :key="o.order_no" class="src-line">
                    <span class="src-no">{{ o.order_no }}</span>
                    <span class="src-qty">{{ qtyDisplayText(o.quantity) }}{{ m.unit ? ` ${m.unit}` : '' }}</span>
                  </div>
                </template>
                <span v-else class="src-empty">—</span>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
    <!-- 底部操作条已删（2026-10-31 用户要求）：导出/打印移至头部右侧（SummaryPanel），
         返回按钮也在头部，页签内不再有操作条。 -->
  </div>
</template>

<script setup lang="ts">
/* 2026-10-31 整页化第二轮：导出/打印/返回按钮移到 SummaryPanel 头部，
   本页签不再有操作条，也无自有事件（原 close/exportSupplier/printSupplier 已删）。 */
import { qtyDisplayText } from '../composables/useSummaryModal'
import type { MaterialItem, SupplierSummaryData } from '../composables/useSummaryModal'

defineProps<{
  supplierData: SupplierSummaryData
  orderCount: number
  supplierGroups: { supplierName: string; materials: MaterialItem[] }[]
}>()

/** 来源订单逐单明细（旧后端不返回 orders 时为空数组 → 显示 —）。 */
function orderLines(m: MaterialItem): { order_no: string; quantity: number }[] {
  return m.orders || []
}
</script>

<style scoped lang="scss">
/*
  表格外观（边框 / 内边距 / 居中对齐）与工厂页签同源，见 summary-tables.scss。
  本组件自 SummaryModal.vue 抽出后，父组件的 scoped `table th, table td` 规则
  不再穿透到此处，必须显式引入，否则表格会丢失边框（本次补齐）。
*/
@use '@/styles/summary-tables.scss' as *;

/* 整页化后的页签骨架（与 SummaryFactoryTab 对称）：
   自身 flex 列撑满父级 .sm-body，表格容器是唯一滚动区。 */
.sms-tab {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  padding: 8px 12px;
}
/* 概要行：单行紧凑文字，不再用渐变条占两行高度 */
.sms-toolbar {
  display: flex;
  align-items: center;
  margin-bottom: 6px;
}
.sms-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
/* 来源订单列：单号加粗蓝、数量浅灰，行内平铺；间距 12px 与效果图一致 */
.src-orders {
  text-align: left;
}
.src-line {
  display: flex;
  align-items: baseline;
  gap: 12px;
  padding: 2px 0;
  font-size: 12px;
  line-height: 1.5;
}
.src-no {
  color: var(--color-primary-600);
  font-weight: 700;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.src-qty {
  color: var(--color-text-muted);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.src-empty {
  color: var(--color-text-muted);
}
</style>
