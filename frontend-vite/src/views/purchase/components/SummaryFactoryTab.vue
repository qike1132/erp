<template>
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
        <div class="relative flex flex-col items-end gap-0.5">
          <div class="flex items-center gap-2">
            <label class="text-xs text-text-secondary whitespace-nowrap">统一损耗率（千分之几）</label>
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
          <!--
            提示位必须「不参与布局」：既不能内联在输入框后（文案出现/消失会改变行宽，
            把整行左右推挤 → 输入一次数字抖动一次），也不能在列内占一行高度
            （列变两行后会比左侧按钮高，items-center 居中会让输入框与按钮上下错位）。
            故绝对定位在输入框下方，只做覆盖显示：行宽、行高、按钮与输入框的垂直居中都不变。
          -->
          <span
            class="sm-loss-hint absolute right-0 top-full mt-0.5 text-[11px] leading-4 whitespace-nowrap"
          >
            <span v-if="lossRateSaveState === 'saving'" class="text-text-muted">保存中…</span>
            <span v-else-if="lossRateSaveState === 'error'" class="text-danger-500">保存失败</span>
            <span v-else-if="lossRateMixed" class="text-text-muted">各订单损耗率不一致</span>
          </span>
        </div>
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
    <table class="w-full border-collapse font-sans text-[13px] bg-white">
      <thead>
        <tr class="bg-border-light">
          <th class="w-[9%]">客户</th>
          <th class="w-[15%]">产品名称</th>
          <th class="w-[7%]">订单数量</th>
          <th class="w-[7%]">备品数量</th>
          <th class="w-[10%]">供应商</th>
          <th class="w-[16%]">布料名称</th>
          <th class="w-[12%]">规格型号</th>
          <th class="w-[6%]">损耗率</th>
          <th class="w-[8%]">数量</th>
          <th class="w-[6%]">单位</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in flatFactoryRows" :key="`${row.gi}-${row.si}-${row.fi}`">
          <td v-if="row.isFirstFabricRow" :rowspan="row.groupFabricCount" class="font-bold">{{ row.group.customer_name }}</td>
          <!-- 逐 SKU 分行：多 SKU 时每 SKU 一行 + 「合计」子行（合计取订单级真值）；
               单 SKU 时仅一行，与改动前逐字一致。产品名称 / 订单数量两列同源，见 buildSkuDisplayLines。 -->
          <td v-if="row.isFirstFabricRow" :rowspan="row.groupFabricCount">
            <div
              v-for="(line, li) in groupSkuLines[row.gi]"
              :key="`n-${li}`"
              :class="['sm-sku-line', { 'sm-sku-line--total': line.isTotal }]"
            >{{ line.name }}</div>
          </td>
          <td v-if="row.isFirstFabricRow" :rowspan="row.groupFabricCount">
            <div
              v-for="(line, li) in groupSkuLines[row.gi]"
              :key="`q-${li}`"
              :class="['sm-sku-line', { 'sm-sku-line--total': line.isTotal }]"
            >{{ formatQty(line.qty) }}</div>
          </td>
          <!-- 备品数量：口径 A（只用分组订单级率），逐 SKU 与「订单数量」同源分行；
               **逐布料行（自定义）损耗率不影响本列** —— 那是材料损耗量级。 -->
          <td v-if="row.isFirstFabricRow" :rowspan="row.groupFabricCount">
            <div
              v-for="(line, li) in groupSkuLines[row.gi]"
              :key="`sp-${li}`"
              :class="['sm-sku-line', { 'sm-sku-line--total': line.isTotal }]"
            >{{ formatQty(line.spare) }}</div>
          </td>
          <td v-if="row.isFirstSupplier" :rowspan="row.supplierFabricCount">{{ row.supplier.supplier_name }}</td>
          <td>{{ row.fabric.fabric_name }}</td>
          <td>{{ row.fabric.specification || '' }}</td>
          <td>
            <template v-if="!editMode">
              <input
                type="number"
                class="w-14 text-right py-1 px-1 text-[13px] border border-border rounded focus:outline-none focus-visible:outline-2 focus-visible:outline-primary-500 focus-visible:outline-offset-2 focus:border-primary-500"
                :value="rateForFabric(row.gi, row.si, row.fi)"
                min="0"
                max="1000"
                step="any"
                @input="onFabricLossRateInput(row.gi, row.si, row.fi, $event)"
              />
              <span
                v-if="isFabricRateMixed(row.gi, row.si, row.fi)"
                class="text-[10px] text-text-muted whitespace-nowrap"
              >不一致</span>
            </template>
            <template v-else>
              {{ formatQty(rateForFabric(row.gi, row.si, row.fi)) }}
            </template>
          </td>
          <td>
            <template v-if="editMode">
              <input
                type="number"
                class="w-20 text-right py-1 px-1.5 text-[13px] inline-block border border-border rounded focus:outline-none focus-visible:outline-2 focus-visible:outline-primary-500 focus-visible:outline-offset-2 focus:border-primary-500"
                :value="editFabricQty(row.fabric, row.gi, row.si, row.fi)"
                min="0"
                @change="$emit('updateQty', row.gi, row.si, row.fi, ($event.target as HTMLInputElement).value)"
                @focus="($event.target as HTMLInputElement).select()"
              />
            </template>
            <template v-else>
              {{ displayFabricQty(row.fabric, row.gi, row.si, row.fi) }}
            </template>
          </td>
          <td>{{ row.fabric.unit || '' }}</td>
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

<script setup lang="ts">
/**
 * SummaryFactoryTab.vue — 汇总下单弹窗「工厂内部订单」页签。
 *
 * 损耗率粒度（**两种率语义不同，不可互换**）：
 * - 顶部「统一损耗率」→ **订单级率**：批量快捷入口，同时驱动供应商页放大、
 *   订单级损耗率落库，以及**「备品数量」列**（备品 = ceil(订单数量 × 订单级率‰)）；
 * - 表格内「损耗率」列 → **逐布料行的材料损耗率**：只驱动该行「数量」列的加放
 *   （实测 400-1000‰，即 40%-100%），**不影响备品** —— 两者差 1-2 个数量级，
 *   混用会虚高（2026-09-30 生产实证：单张单备品 150 → 4500）。
 */
import { computed } from 'vue'
import { fmtQty as formatQty } from '@/utils/formatQty'
import { factoryQtyDisplayValue, buildSkuDisplayLines } from '../composables/useSummaryModal'
import type { FactorySummaryData, FactoryGroup, SupplierGroup, FabricItem, SkuDisplayLine } from '../composables/useSummaryModal'

const props = defineProps<{
  factoryData: FactorySummaryData
  editMode: boolean
  lossRate: number
  orderCount: number
  /** 损耗率自动落库的可见反馈状态（缺省视为 idle；由 useSummaryModal 提供） */
  lossRateSaveState?: 'idle' | 'saving' | 'saved' | 'error'
  /** 各单损耗率不一致（缺省视为 false；由 useSummaryModal 提供）→ 输入框旁提示 */
  lossRateMixed?: boolean
  /** 每个布料行当前的损耗率，形状 [gi][si][fi]；缺省回退 lossRate */
  fabricLossRates?: number[][][]
  /** 每个布料行内各明细损耗率是否不一致，形状 [gi][si][fi] */
  fabricLossRateMixed?: boolean[][][]
  /** 每个分组的订单级损耗率（「备品数量」列的唯一口径），形状 [gi]；缺省回退 lossRate */
  groupSpareRates?: number[]
}>()

const emit = defineEmits<{
  close: []
  toggleEditMode: [enable: boolean]
  saveEdits: []
  updateQty: [gi: number | string, si: number | string, fi: number | string, value: string]
  /** 统一损耗率输入的归一化值（已夹取到 0..1000）。防抖由父组件负责。 */
  lossRateInput: [rate: number]
  /** 单个布料行损耗率输入的归一化值（已夹取到 0..1000）。防抖由父组件负责。 */
  fabricLossRateInput: [gi: number, si: number, fi: number, rate: number]
  exportFactory: []
  printFactory: []
}>()

/**
 * 只做归一化，不做防抖：防抖必须留在父组件（SummaryModal）的 setup 作用域。
 */
function onLossRateInput(e: Event) {
  const val = parseFloat((e.target as HTMLInputElement).value)
  if (isNaN(val) || val < 0) {
    emit('lossRateInput', 0)
    return
  }
  emit('lossRateInput', Math.min(val, 1000))
}

function onFabricLossRateInput(gi: number, si: number, fi: number, e: Event) {
  const val = parseFloat((e.target as HTMLInputElement).value)
  if (isNaN(val) || val < 0) {
    emit('fabricLossRateInput', gi, si, fi, 0)
    return
  }
  emit('fabricLossRateInput', gi, si, fi, Math.min(val, 1000))
}

/** 取第 gi/si/fi 个布料行当前损耗率；未提供时回退统一损耗率。 */
function rateForFabric(gi: number, si: number, fi: number): number {
  const v = props.fabricLossRates?.[gi]?.[si]?.[fi]
  return typeof v === 'number' && Number.isFinite(v) ? v : props.lossRate
}

function isFabricRateMixed(gi: number, si: number, fi: number): boolean {
  return props.fabricLossRateMixed?.[gi]?.[si]?.[fi] === true
}

/**
 * 非编辑态「数量」列展示值：原始数量按该行损耗率加放后向上取整为整数（不写回数据）。
 * 编辑态输入框使用 editFabricQty 加载精确加放值，避免「展示取整」污染落库真值；
 * 用户提交时由 useSummaryModal.updateFactoryQty 按该行损耗率反推原始真值后再落库。
 */
function displayFabricQty(fabric: FabricItem, gi: number, si: number, fi: number): number {
  return factoryQtyDisplayValue(parseFloat(String(fabric.quantity)) || 0, rateForFabric(gi, si, fi), false)
}

/** 编辑态「数量」输入框值：保留损耗加放后的精确派生值，供保存时无损反推。 */
function editFabricQty(fabric: FabricItem, gi: number, si: number, fi: number): number {
  return factoryQtyDisplayValue(parseFloat(String(fabric.quantity)) || 0, rateForFabric(gi, si, fi), true)
}

/**
 * 该分组的订单级率（「备品数量」列的唯一口径）：分组值优先，缺省回退顶部「统一损耗率」。
 * 注意：**不读 `fabricLossRates`** —— 逐布料行的材料损耗率不得影响备品（见文件头说明）。
 */
function spareRateForGroup(gi: number): number {
  const v = props.groupSpareRates?.[gi]
  return typeof v === 'number' && Number.isFinite(v) ? v : props.lossRate
}

/**
 * 每个汇总分组的逐 SKU 展示行（按 gi 索引，供「产品名称 / 订单数量 / 备品数量」三列共用）。
 */
const groupSkuLines = computed<SkuDisplayLine[][]>(() =>
  (props.factoryData?.groups || []).map((g, gi) => buildSkuDisplayLines(g, spareRateForGroup(gi))),
)

// 预计算 flatFactoryRows，避免模板内每行调用 isFirstFabricRow/getGroupFabricCount
const flatFactoryRows = computed(() => {
  const rows: {
    gi: number; si: number; fi: number
    group: FactoryGroup
    supplier: SupplierGroup
    fabric: FabricItem
    isFirstFabricRow: boolean
    groupFabricCount: number
    isFirstSupplier: boolean
    supplierFabricCount: number
  }[] = []
  const groups = props.factoryData?.groups || []
  groups.forEach((group, gi) => {
    const suppliers = group.suppliers || []
    const groupFabricCount = suppliers.reduce((s, sup) => s + (sup.fabrics?.length || 0), 0)
    suppliers.forEach((supplier, si) => {
      const fabrics = supplier.fabrics || []
      fabrics.forEach((fabric, fi) => {
        rows.push({
          gi, si, fi, group, supplier, fabric,
          isFirstFabricRow: fi === 0 && si === 0,
          groupFabricCount,
          isFirstSupplier: fi === 0,
          supplierFabricCount: fabrics.length,
        })
      })
    })
  })
  return rows
})
</script>

<style scoped lang="scss">
@use '@/styles/summary-tables.scss' as *;

/*
  逐 SKU 分行（产品名称 / 订单数量 两列共用）：
  - 单 SKU 时只有一行 → 不产生任何分隔线，视觉与改动前一致（零回归）；
  - 多 SKU 时行间加细分隔线，末行「合计」加粗，便于与逐 SKU 明细区分；
  - 无动效、无额外留白，保持工厂表格的紧凑密度。
*/
.sm-sku-line {
  line-height: 1.5;
  white-space: normal;
  word-break: break-word;
}
.sm-sku-line + .sm-sku-line {
  margin-top: 2px;
  padding-top: 2px;
  border-top: 1px dashed var(--color-border-light);
}
.sm-sku-line--total {
  font-weight: bold;
}
</style>
