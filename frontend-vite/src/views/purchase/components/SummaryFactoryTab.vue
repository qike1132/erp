<template>
  <!-- 整页视图内的页签：自身也是 flex 列（父级 .sm-body 是 flex），
       中段表格是唯一滚动区（flex:1 + min-h:0 撑满剩余高度），顶部概要行常驻；
       底部操作条已删（导出/打印/返回都在头部）。 -->
  <div class="smf-tab">
    <!-- 概要行（2026-10-31 用户嫌空白多）：删渐变底色大条，压成单行紧凑文字+操作。
         「工厂内部采购订单汇总」标题删掉——页签已说明所在；只保留订单计数。 -->
    <div class="smf-toolbar flex-shrink-0">
      <div class="text-[13px] text-text-secondary whitespace-nowrap">
        已选择 <strong class="text-primary-400">{{ factoryData.order_count || orderCount }}</strong> 个订单
      </div>
      <div class="flex gap-2 items-center ml-auto">
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
          <!-- F1a-02（2026-10-24 审计）：加在途禁用——接口幂等不致错账，但双击
             会交错改写基线并发多一次写；lossRateSaveState 由 useSummaryModal 维护。 -->
          <button
            class="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium text-white bg-success-500 rounded-lg border-none transition-colors hover:bg-success-600 disabled:opacity-60 disabled:cursor-not-allowed"
            :disabled="lossRateSaveState === 'saving'"
            @click="$emit('saveEdits')"
          >
            <FontAwesomeIcon icon="save" aria-hidden="true" /> {{ lossRateSaveState === 'saving' ? '保存中…' : '保存修改' }}
          </button>
        </template>
      </div>
    </div>

    <div class="smf-scroll">
      <!-- 2026-10-31 用户反馈：不铺满、但也不要太小——取 82% 宽度居中，
           比例适中；窄屏由 min-w 兜底（容器内可横向滚动）。 -->
      <table class="w-[82%] min-w-[900px] mx-auto border-collapse font-sans text-[13px] bg-white">
        <thead>
          <tr class="bg-border-light">
            <th>客户</th>
            <th class="w-[280px]">产品名称</th>
            <th>订单数量</th>
            <th>备品数量</th>
            <th>供应商</th>
            <th class="w-[200px]">布料名称</th>
            <th>规格型号</th>
            <th>损耗率</th>
            <th>数量</th>
            <th>单位</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="(item, ri) in flatRows" :key="`${item.gi}-${ri}`">
            <tr>
              <!-- 客户：该组第一行，rowspan = 该组总行数（两种模式同一算法） -->
              <td v-if="isGroupFirstRow(item.gi, ri)" :rowspan="groupRowCounts[item.gi]" class="font-bold">
                {{ item.group.customer_name }}
              </td>

              <!-- 产品名称 / 订单数量 / 备品数量：该 SKU 块首行，rowspan = 该块行数。
                 cellLines 在 per-SKU 模式恒 1 行；回退模式为逐 SKU 名堆叠（与改动前逐字一致）。 -->
              <td v-if="item.row.isFirstSkuRow" :rowspan="item.row.skuRowSpan">
                <div v-for="(line, li) in item.row.cellLines" :key="`n-${li}`"
                     :class="['sm-sku-line', { 'sm-sku-line--total': line.isTotal }]"
                >{{ line.name }}</div>
              </td>
              <td v-if="item.row.isFirstSkuRow" :rowspan="item.row.skuRowSpan">
                <div v-for="(line, li) in item.row.cellLines" :key="`q-${li}`"
                     :class="['sm-sku-line', { 'sm-sku-line--total': line.isTotal }]"
                >{{ formatQty(line.qty) }}</div>
              </td>
              <td v-if="item.row.isFirstSkuRow" :rowspan="item.row.skuRowSpan">
                <div v-for="(line, li) in item.row.cellLines" :key="`sp-${li}`"
                     :class="['sm-sku-line', { 'sm-sku-line--total': line.isTotal }]"
                >{{ formatQty(line.spare) }}</div>
              </td>

              <!-- 该 SKU 无 BOM：占位行（保留块结构，不隐藏该 SKU） -->
              <td v-if="item.row.noBom" colspan="6" class="text-text-muted">无 BOM 明细</td>

              <template v-else>
                <!-- 供应商：块内首行 -->
                <td v-if="item.row.isFirstSupplierRow" :rowspan="item.row.supplierRowSpan">{{ item.row.supplierName }}</td>
                <td>{{ item.row.materialName }}</td>
                <td>{{ item.row.specification || '' }}</td>
                <!-- 损耗率：有落库坐标才可编辑；无坐标 → 只读并说明原因 -->
                <td>
                  <template v-if="rowCoord(item)">
                    <!-- 非编辑态：率输入框 +「不一致」提示同处一支（与改造前逐字一致；提示仅非编辑态显示） -->
                    <template v-if="!editMode">
                      <input
                        type="number" class="w-14 text-right py-1 px-1 text-[13px] border border-border rounded focus:outline-none focus-visible:outline-2 focus-visible:outline-primary-500 focus-visible:outline-offset-2 focus:border-primary-500"
                        :value="rowRate(item)" min="0" max="1000" step="any"
                        :title="sharedMaterialTitle(item)"
                        @input="onRowRateInput(item, $event)"
                      />
                      <span v-if="isRowRateMixed(item)" class="text-[10px] text-text-muted whitespace-nowrap">不一致</span>
                    </template>
                    <template v-else>{{ formatQty(rowRate(item)) }}</template>
                  </template>
                  <span v-else class="text-text-muted" title="该物料不在采购明细中（BOM 生成后新增），无法在此修改">—</span>
                </td>
                <!-- 数量：编辑态可改（同物料跨 SKU 联动，故给出提示）；否则取派生展示值 -->
                <td>
                  <input
                    v-if="rowCoord(item) && editMode"
                    type="number" class="w-20 text-right py-1 px-1.5 text-[13px] inline-block border border-border rounded focus:outline-none focus-visible:outline-2 focus-visible:outline-primary-500 focus-visible:outline-offset-2 focus:border-primary-500"
                    :value="editRowQty(item)" min="0"
                    :title="sharedMaterialTitle(item)"
                    @change="onRowQtyChange(item, $event)"
                    @focus="($event.target as HTMLInputElement).select()"
                  />
                  <template v-else>{{ displayRowQty(item) }}</template>
                </td>
                <td>{{ item.row.unit || '' }}</td>
              </template>
            </tr>

            <!-- 数量差异对照块：仅该组最后一行、且该组存在「推算 vs 落库」差异时渲染（无差异不占高度） -->
            <SummaryDiffBlock
              v-if="rowDiffMap[item.gi] && rowDiffMap[item.gi]!.length > 0 && isLastRowOfGroup(item.gi, ri)"
              :diffs="rowDiffMap[item.gi]!"
              :stored-rows="storedRowsOf(item.group, item.gi)"
            />
          </template>
        </tbody>
      </table>
    </div>
    <!-- 底部操作条已删（2026-10-31 用户要求）：导出/打印移至头部右侧（SummaryPanel），
         返回按钮也在头部，页签内不再有操作条。 -->
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
import { fmtQty as formatQty } from '@/utils/formatQty'
import { useFactoryTableRows } from '../composables/useFactoryTableRows'
import type { FactoryTabEmit, FactoryTabProps } from '../composables/useFactoryTableRows'
import SummaryDiffBlock from './SummaryDiffBlock.vue'

const props = defineProps<FactoryTabProps>()

const emit = defineEmits<FactoryTabEmit>()

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

// 行模型与率/数量读写胶水（2026-09-30 抽到 useFactoryTableRows.ts，以守住单 .vue ≤ 400 行门禁）
const {
  flatRows, rowDiffMap, storedRowsOf, isLastRowOfGroup, groupRowCounts, isGroupFirstRow, rowCoord, rowRate,
  editRowQty, displayRowQty, sharedMaterialTitle, isRowRateMixed, onRowRateInput, onRowQtyChange,
} = useFactoryTableRows(props, emit)
</script>

<style scoped lang="scss">
@use '@/styles/summary-tables.scss' as *;

/* 整页化后的页签骨架（与 SummarySupplierTab 对称）：
   自身 flex 列撑满父级 .sm-body，表格容器是唯一滚动区。 */
.smf-tab {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  padding: 8px 12px;
}
/* 概要行：单行紧凑（数字+操作按钮），不再用渐变条占两行高度 */
.smf-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 6px;
}
.smf-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

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
