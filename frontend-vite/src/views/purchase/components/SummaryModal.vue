<template>
  <UiDialog :open="open" class="max-w-[1000px]" @update:open="$emit('close')">
    <template #title>
      <div class="flex items-center gap-2"><FontAwesomeIcon icon="clipboard-list" class="text-primary-500" aria-hidden="true" /> 汇总下单</div>
    </template>

    <!-- Tab headers -->
    <div class="sm-tab-group" role="tablist">
      <div
        role="tab"
        :aria-selected="activeTab === 'factory'"
        :class="['sm-tab-btn', { active: activeTab === 'factory' }]"
        @click="activeTab = 'factory'"
      >
        <FontAwesomeIcon icon="industry" aria-hidden="true" /> 工厂内部订单
      </div>
      <div
        role="tab"
        :aria-selected="activeTab === 'supplier'"
        :class="['sm-tab-btn', { active: activeTab === 'supplier', 'out-mode': activeTab === 'supplier' }]"
        @click="activeTab = 'supplier'"
      >
        <FontAwesomeIcon icon="truck" aria-hidden="true" /> 供应商采购订单
      </div>
    </div>

    <div class="py-4">
      <!-- Factory Tab -->
      <template v-if="activeTab === 'factory' && factoryData">
        <div
          class="mb-3 p-3 rounded-lg flex justify-between items-center bg-gradient-to-r from-primary-400/10 to-purple-600/10"
        >
          <div>
            <div class="font-semibold text-sm mb-1.5">
              <FontAwesomeIcon icon="industry" class="text-primary-400" aria-hidden="true" /> 工厂内部采购订单汇总
            </div>
            <div class="text-xs text-text-secondary">
              已选择 <strong class="text-primary-400">{{ factoryData.order_count || orderCount }}</strong> 个订单
            </div>
          </div>
          <div class="flex gap-2 items-center">
            <div v-if="!editMode" class="flex items-center gap-2">
              <button
                class="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium rounded-lg border border-border bg-transparent text-text-secondary hover:text-primary-500 hover:border-primary-500 hover:bg-primary-50 transition-colors"
                @click="$emit('toggleEditMode', true)"
              >
                <FontAwesomeIcon icon="edit" aria-hidden="true" /> 自定义编辑
              </button>
              <label class="text-xs text-text-secondary whitespace-nowrap">损耗率（千分之几）</label>
              <input
                type="number"
                class="w-16 text-right py-1 px-1.5 text-[13px] border border-border rounded focus:outline-none focus-visible:outline-2 focus-visible:outline-primary-500 focus-visible:outline-offset-2 focus:border-primary-500"
                :value="lossRate"
                min="0"
                max="1000"
                step="any"
                @input="onLossRateInput"
              />
            </div>
            <template v-else>
              <button
                class="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium text-white bg-warning-500 rounded-lg border-none transition-colors hover:bg-warning-600"
                @click="$emit('toggleEditMode', false)"
              >
                <FontAwesomeIcon icon="times" aria-hidden="true" /> 取消编辑
              </button>
              <button
                class="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium text-white bg-success-500 rounded-lg border-none transition-colors hover:bg-success-600"
                @click="$emit('saveEdits')"
              >
                <FontAwesomeIcon icon="save" aria-hidden="true" /> 保存修改
              </button>
            </template>
          </div>
        </div>

        <div class="max-h-[calc(100vh-320px)] overflow-auto">
          <table class="w-full border-collapse font-[SimSun,_宋体] text-[13px] bg-white">
            <thead>
              <tr class="bg-border-light">
                <th class="w-[10%]">客户</th>
                <th class="w-[16%]">产品名称</th>
                <th class="w-[7%]">订单数量</th>
                <th class="w-[10%]">供应商</th>
                <th class="w-[25%]">布料名称</th>
                <th class="w-[17%]">规格型号</th>
                <th class="w-[15%]">数量</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="(group, gi) in factoryData.groups || []" :key="gi">
                <template v-for="(supplier, si) in group.suppliers || []" :key="si">
                  <tr v-for="(fabric, fi) in supplier.fabrics || []" :key="fi">
                    <td v-if="isFirstFabricRow(gi, si, fi)" :rowspan="getGroupFabricCount(gi)" class="font-bold">
                      {{ group.customer_name }}
                    </td>
                    <td v-if="isFirstFabricRow(gi, si, fi)" :rowspan="getGroupFabricCount(gi)">
                      {{ group.product_name }}
                    </td>
                    <td v-if="isFirstFabricRow(gi, si, fi)" :rowspan="getGroupFabricCount(gi)">
                      {{ formatQty(group.product_quantity || group.order_quantity) }}
                    </td>
                    <td v-if="fi === 0" :rowspan="supplier.fabrics.length">
                      {{ supplier.supplier_name }}
                    </td>
                    <td>{{ fabric.fabric_name }}</td>
                    <td>{{ fabric.specification || '' }}</td>
                    <td class="text-right">
                      <template v-if="editMode">
                        <input
                          type="number"
                          class="w-20 text-right py-1 px-1.5 text-[13px] inline-block border border-border rounded focus:outline-none focus-visible:outline-2 focus-visible:outline-primary-500 focus-visible:outline-offset-2 focus:border-primary-500"
                          :value="fabric.quantity"
                          min="0"
                          @change="$emit('updateQty', gi, si, fi, ($event.target as HTMLInputElement).value)"
                          @focus="($event.target as HTMLInputElement).select()"
                        />
                        <span class="text-xs ml-0.5">{{ fabric.unit || '' }}</span>
                      </template>
                      <template v-else>
                        {{ formatQty(fabric.quantity) }} {{ fabric.unit || '' }}
                      </template>
                    </td>
                  </tr>
                </template>
              </template>
              <tr class="bg-border-light font-bold">
                <td colspan="4" class="text-center">合计</td>
                <td />
                <td />
                <td class="text-right">
                  {{ formatQty(factoryGrandTotal) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="mt-4 pt-3 border-t border-border flex justify-between items-center">
          <div class="flex gap-2">
            <button
              class="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium text-white bg-success-500 rounded-lg border-none transition-colors hover:bg-success-600"
              @click="$emit('exportFactory')"
            >
              <FontAwesomeIcon icon="file-excel" aria-hidden="true" /> 导出 Excel
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
              @click="$emit('printFactory')"
            >
              <FontAwesomeIcon icon="print" aria-hidden="true" /> 打印预览
            </button>
          </div>
        </div>
      </template>

      <!-- Supplier Tab -->
      <template v-if="activeTab === 'supplier' && supplierData">
        <div
          class="mb-3 p-3 rounded-lg flex justify-between items-center bg-gradient-to-r from-rose/10 to-rose-deep/10"
        >
          <div>
            <div class="font-semibold text-sm mb-1.5"><FontAwesomeIcon icon="truck" class="text-rose" aria-hidden="true" /> 供应商采购订单汇总</div>
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
                  <td class="text-right">{{ formatQty(m.total_quantity) }} {{ m.unit || '' }}</td>
                </tr>
              </template>
              <tr class="bg-border-light font-bold">
                <td class="text-center">合计</td>
                <td />
                <td />
                <td class="text-right">
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
    </div>
  </UiDialog>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import { fmtQty as formatQty } from '@/utils/formatQty'

const props = defineProps<{
  open: boolean
  factoryData: any
  supplierData: any
  editMode: boolean
  lossRate: number
  orderCount: number
  supplierGroups: { supplierName: string; materials: any[] }[]
}>()

const emit = defineEmits<{
  close: []
  toggleEditMode: [enable: boolean]
  saveEdits: []
  updateQty: [gi: number | string, si: number | string, fi: number | string, value: string]
  applyLossRate: [rate: number]
  exportFactory: []
  exportSupplier: []
  printFactory: []
  printSupplier: []
}>()

const activeTab = ref<'factory' | 'supplier'>('factory')

function onLossRateInput(e: Event) {
  const val = parseFloat((e.target as HTMLInputElement).value)
  if (isNaN(val) || val < 0) {
    emit('applyLossRate', 0)
    return
  }
  emit('applyLossRate', Math.min(val, 1000))
}

const factoryGrandTotal = computed(() => {
  let t = 0
  props.factoryData?.groups?.forEach((g: any) =>
    g.suppliers?.forEach((s: any) => s.fabrics?.forEach((f: any) => (t += parseFloat(f.quantity) || 0))),
  )
  return t
})

const supplierGrandTotal = computed(() => {
  let t = 0
  props.supplierGroups.forEach((g) => g.materials.forEach((m) => (t += parseFloat(m.total_quantity) || 0)))
  return t
})

function isFirstFabricRow(gi: number | string, si: number | string, fi: number | string): boolean {
  return Number(fi) === 0 && Number(si) === 0
}

function getGroupFabricCount(gi: number | string): number {
  const group = props.factoryData?.groups?.[Number(gi)]
  if (!group) return 1
  return (group.suppliers || []).reduce((sum: number, s: any) => sum + (s.fabrics?.length || 0), 0)
}
</script>

<style scoped>
.sm-tab-group {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  margin-bottom: 12px;
}
.sm-tab-btn {
  padding: 8px 14px;
  border: none;
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  background: transparent;
  cursor: pointer;
  transition: color 0.3s ease, background 0.3s ease;
  display: flex;
  align-items: center;
  gap: 6px;
}
.sm-tab-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}
.sm-tab-btn.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91, 141, 239, 0.2);
  transform: translateY(-1px);
}
.sm-tab-btn.active.out-mode {
  background: linear-gradient(135deg, var(--color-danger-50), var(--color-danger-100));
  color: var(--color-danger-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(234, 84, 85, 0.2);
}

table th,
table td {
  border: 1px solid var(--color-text);
  padding: 8px;
  vertical-align: middle;
}
table th {
  font-weight: bold;
  text-align: center;
}
</style>
