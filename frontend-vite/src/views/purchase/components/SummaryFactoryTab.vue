<template>
  <!-- 整页视图内的页签：自身也是 flex 列（父级 .sm-body 是 flex），
       中段表格是唯一滚动区（flex:1 + min-h:0 撑满剩余高度），顶部概要行常驻；
       底部操作条已删（导出/打印/返回都在头部）。 -->
  <div class="smf-tab">
    <!-- 概要行（2026-10-31 用户嫌空白多）：删渐变底色大条，压成单行紧凑文字+操作。
         「工厂内部采购订单汇总」标题删掉——页签已说明所在；只保留订单计数。
         2026-11-13 用户要求：「统一损耗率」输入框并入表格「损耗率」表头，
         本行不再承载输入控件，只留订单计数与（绝对定位的）落库状态提示。 -->
    <div class="smf-toolbar flex-shrink-0">
      <div class="text-[14px] text-text-secondary whitespace-nowrap">
        已选择 <strong class="text-primary-400">{{ factoryData.order_count || orderCount }}</strong> 个订单
      </div>
      <!--
      提示位必须「不参与布局」：文案出现/消失若参与布局，会把左侧计数左右推挤。
      故绝对定位在概览行右侧、垂直居中，只做覆盖显示：行宽、行高都不变。
      （原先它挂在输入框下方；输入框迁到表头后，锚点改为概览行本身。）
    -->
      <span
        class="sm-loss-hint absolute right-0 top-1/2 text-[12px] leading-4 whitespace-nowrap"
      >
        <span v-if="lossRateSaveState === 'saving'" class="text-text-muted">保存中…</span>
        <span v-else-if="lossRateSaveState === 'error'" class="text-danger-500">保存失败</span>
        <span v-else-if="lossRateMixed" class="text-text-muted">各订单损耗率不一致</span>
      </span>
    </div>

    <div class="smf-scroll">
      <!-- 2026-10-31 用户反馈：不铺满、但也不要太小——取 82% 宽度居中，
           比例适中；窄屏由 min-w 兜底（容器内可横向滚动）。 -->
      <table class="w-[82%] min-w-[900px] mx-auto border-collapse font-sans text-[14px] bg-white">
        <thead>
          <tr class="bg-border-light">
            <th>客户</th>
            <th class="w-[240px]">产品名称</th>
            <!-- 2026-11-08 用户要求：角色名称在「订单数量」左边；隐藏款标记挂在角色名称上。
                 该列只在「多角色产品」时显示（单角色/无角色订单隐藏，整表按数据判定）。 -->
            <th v-if="showRoleColumn">角色名称</th>
            <th>订单数量</th>
            <th>备品数量</th>
            <!-- 2026-11-05 用户要求：产品部位在供应商之前（屏幕 / 打印 / 导出同序） -->
            <th>产品部位</th>
            <th>供应商</th>
            <th class="w-[180px]">布料名称</th>
            <th>规格型号</th>
            <!-- 损耗率表头 = 列名 + 「统一损耗率」输入**合成一格**（2026-11-13 用户要求「融为一体」）。
                 两种率语义不同、数量级差 1-2 个（见文件头注释），故保留「统一」小字 +
                 title 全量说明：本格是订单级率（驱动备品数量与供应商页放大），
                 下方每行的「损耗率」才是该行材料率（只驱动该行数量）。 -->
            <th class="sm-rate-head" :title="UNIFIED_RATE_TITLE">
              <span class="sm-rate-head__label">损耗率</span>
              <span class="sm-rate-head__field">
                <span class="sm-rate-head__cap">统一</span>
                <input
                  type="number"
                  class="sm-rate-head__input"
                  :value="lossRate"
                  min="0"
                  max="1000"
                  step="any"
                  inputmode="decimal"
                  aria-label="工厂内部订单统一损耗率（千分之几）"
                  @input="onLossRateInput"
                  @wheel="onRateWheel"
                />
                <span class="sm-rate-head__unit" aria-hidden="true">‰</span>
              </span>
            </th>
            <th
              class="sm-qty-col"
              title="自定义数量仅对当前采购订单生效，不写入 BOM；新订单仍按 BOM 用量计算"
            >数量</th>
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

              <!-- 产品名称 / 角色名称 / 订单数量 / 备品数量：该 SKU 块首行，rowspan = 该块行数。
                 cellLines 在 per-SKU 模式恒 1 行；回退模式为逐 SKU 名堆叠（与改动前逐字一致）。
                 列序（2026-11-08 用户要求）：角色名称在「订单数量」左边，隐藏款标记挂在
                 角色名称格上；「订单数量/备品数量」按角色段拆分时 SKU 总量挪到名称格副行
                 （合计 N），数量列在每个角色段渲染该角色的数量与备品。 -->
              <td v-if="item.row.isFirstSkuRow" :rowspan="item.row.skuRowSpan">
                <div v-for="(line, li) in item.row.cellLines" :key="`n-${li}`"
                     :class="['sm-sku-line', { 'sm-sku-line--total': line.isTotal }]"
                >{{ line.name }}</div>
                <div v-if="item.row.hasRoleQtySplit" class="sm-sku-total-sub">合计 {{ formatQty(item.row.cellLines[0]?.qty) }}</div>
              </td>
              <!-- 角色名称：角色段首行（rowspan=段行数）；隐藏款标记显示在角色名上；
                   单角色/无角色订单不渲染该列（整表隐藏） -->
              <td
                v-if="showRoleColumn && item.row.isFirstRoleRow"
                :rowspan="item.row.roleRowSpan > 1 ? item.row.roleRowSpan : undefined"
              >
                <div>{{ item.row.roleDisplay }}</div>
                <div v-if="item.row.roleIsHidden" class="sm-sku-total-sub">（隐藏款）</div>
              </td>
              <!-- 订单数量：无角色拆分 → SKU 级大格（原样）；有拆分 → 角色段格
                   （rowspan=roleRowSpan，与角色格同段）。段内行无格（被覆盖）。 -->
              <td
                v-if="item.row.isFirstSkuRow && !item.row.hasRoleQtySplit"
                :rowspan="item.row.skuRowSpan"
              >
                <div v-for="(line, li) in item.row.cellLines" :key="`q-${li}`"
                     :class="['sm-sku-line', { 'sm-sku-line--total': line.isTotal }]"
                >{{ formatQty(line.qty) }}</div>
              </td>
              <td
                v-else-if="item.row.isFirstRoleRow && item.row.roleQuantity != null"
                :rowspan="item.row.roleRowSpan"
              >{{ formatQty(item.row.roleQuantity) }}</td>
              <!-- 备品数量：拆分口径与订单数量同构（每角色段一格，ceil(该角色数量×率‰)） -->
              <td
                v-if="item.row.isFirstSkuRow && !item.row.hasRoleQtySplit"
                :rowspan="item.row.skuRowSpan"
              >
                <div v-for="(line, li) in item.row.cellLines" :key="`sp-${li}`"
                     :class="['sm-sku-line', { 'sm-sku-line--total': line.isTotal }]"
                >{{ formatQty(line.spare) }}</div>
              </td>
              <td
                v-else-if="item.row.isFirstRoleRow && item.row.roleSpare != null"
                :rowspan="item.row.roleRowSpan"
              >{{ formatQty(item.row.roleSpare) }}</td>

              <!-- 该 SKU 无 BOM：占位行（保留块结构，不隐藏该 SKU；角色格已渲染空占位，
                   剩余 部位/供应商/布料/规格/损耗率/数量/单位 = 7 列；隐藏角色列时 8 列） -->
              <td v-if="item.row.noBom" :colspan="showRoleColumn ? 7 : 8" class="text-text-muted">无 BOM 明细</td>

              <template v-else>
                <!-- 列序：产品部位（逐行）→ 供应商（子段首行 + rowspan）。
                     td 顺序必须与 thead 严格一致，否则「表头换了、值串列」；
                     rowspan 按**连续段**计算，跨段的行绝不能被罩住（会错位）。 -->
                <td>{{ item.row.partDisplay }}</td>
                <td v-if="item.row.isFirstSupplierRow" :rowspan="item.row.supplierRowSpan">{{ item.row.supplierName }}</td>
                <td>{{ item.row.materialName }}</td>
                <td>{{ item.row.specification || '' }}</td>
                <!-- 损耗率：有落库坐标即可直接编辑（自动落库），与是否编辑数量无关；
                     无坐标（BOM 新增物料）→ — 并说明原因 -->
                <td>
                  <template v-if="rowCoord(item)">
                    <input
                      type="number" class="sm-inline-input text-right border border-border rounded focus:outline-none focus-visible:outline-2 focus-visible:outline-primary-500 focus-visible:outline-offset-2 focus:border-primary-500"
                      :value="rowRate(item)" min="0" max="1000" step="any"
                      :title="sharedMaterialTitle(item)"
                      @input="onRowRateInput(item, $event)"
                    />
                    <span v-if="isRowRateMixed(item)" class="text-[12px] text-text-muted whitespace-nowrap">不一致</span>
                  </template>
                  <span v-else class="text-text-muted" title="该物料不在采购明细中（BOM 生成后新增），无法在此修改">—</span>
                </td>
                <!-- 数量：点击数字就地编辑（只改该行对应采购明细，保存为行级操作）。
                     多角色共用行锁编辑（明细是合并总量，此处只显示该角色的分配量）。
                     列宽固定，输入框/保存按钮不撑开列宽与行高。 -->
                <td class="sm-qty-col">
                  <template v-if="canEditQty(item)">
                    <div v-if="qtyDraftOf(item) !== undefined" class="sm-qty-editor">
                      <input
                        type="text" inputmode="decimal" autocomplete="off" class="sm-qty-input sm-inline-input text-center border border-border rounded focus:outline-none focus-visible:outline-2 focus-visible:outline-primary-500 focus-visible:outline-offset-2 focus:border-primary-500"
                        :value="qtyDraftOf(item)"
                        :title="qtyEditTitle(item)"
                        :disabled="isQtySaving(item)"
                        @input="onQtyDraftInput(item, $event)"
                        @keydown.enter.prevent="onQtySave(item)"
                        @keydown.esc.prevent="onQtyEsc(item)"
                        @blur="onQtyBlur(item)"
                        @focus="($event.target as HTMLInputElement).select()"
                      />
                      <button
                        v-if="isQtyDraftDirty(item)"
                        class="sm-qty-save" :disabled="qtySavingKey != null"
                        @mousedown.prevent
                        @click="onQtySave(item)"
                      >{{ isQtySaving(item) ? '保存中…' : '保存' }}</button>
                    </div>
                    <span
                      v-else class="sm-qty-cell" role="button" tabindex="0"
                      :title="qtyEditTitle(item)"
                      @click="onQtyCellClick(item)"
                    >{{ displayRowQty(item) }}</span>
                  </template>
                  <span
                    v-else-if="item.row.readonlyReason"
                    class="text-text-muted" :title="item.row.readonlyReason"
                  >{{ displayRowQty(item) }}</span>
                  <template v-else>{{ displayRowQty(item) }}</template>
                </td>
                <td>{{ item.row.unit || '' }}</td>
              </template>
            </tr>

            <!-- 数量差异对照块：仅该组最后一行、且打开汇总时已存在「推算 vs 落库」差异时渲染。
                 2026-11-11 owner 口径：本次会话保存产生的差异不弹横幅（rowDiffMap 在
                 factoryData 整体替换时重新快照；单行数量保存原地改数量不更新快照）。 -->
            <SummaryDiffBlock
              v-if="rowDiffMap[item.gi] && rowDiffMap[item.gi]!.length > 0 && isLastRowOfGroup(item.gi, ri)"
              :diffs="rowDiffMap[item.gi]!"
              :stored-rows="storedRowsOf(item.group, item.gi)"
              :show-role-column="showRoleColumn"
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
import { computed } from 'vue'
import { anyGroupMultiRole } from '../composables/useSummaryModal'
import { useFactoryTableRows } from '../composables/useFactoryTableRows'
import type { FactoryTabEmit, FactoryTabProps } from '../composables/useFactoryTableRows'
import SummaryDiffBlock from './SummaryDiffBlock.vue'

const props = defineProps<FactoryTabProps>()

/**
 * 「角色名称」列是否显示（2026-11-08 用户要求）：只有多角色产品才显示。
 * 整表级判定——任一分组出现 ≥2 个不同角色名即显示；单角色/无角色订单隐藏该列。
 */
const showRoleColumn = computed(() => anyGroupMultiRole(props.factoryData))

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

/**
 * 表头输入获焦后，浏览器会把滚轮动作转成 number 的步进 → 表格滚动时静默改率并自动落库。
 * 该格常驻在滚动区**顶部**，命中概率远高于表体行，故：滚动即失焦并吃掉这一次滚轮
 * （仅影响「已聚焦」这一种状态，未聚焦时滚轮照常滚动表格）。
 */
function onRateWheel(e: WheelEvent) {
  const el = e.currentTarget as HTMLInputElement
  if (document.activeElement !== el) return
  el.blur()
  e.preventDefault()
}

/**
 * 表头「统一损耗率」格的常驻说明（title）：用户悬停整格可见，含单位与
 * 「不影响下方行率」的关键口径——两率混用会导致备品虚高（2026-09-30 生产实证）。
 */
const UNIFIED_RATE_TITLE =
  '统一损耗率（千分之几）：按订单批量作用，决定「备品数量」与供应商页放大；'
  + '表格内每行的「损耗率」是该行材料损耗率，只影响该行数量，两者不可混用'

// 行模型与率/数量读写胶水（2026-09-30 抽到 useFactoryTableRows.ts，以守住单 .vue ≤ 400 行门禁）
const {
  flatRows, rowDiffMap, storedRowsOf, isLastRowOfGroup, groupRowCounts, isGroupFirstRow, rowCoord, rowRate,
  displayRowQty, sharedMaterialTitle, qtyEditTitle, isRowRateMixed, onRowRateInput,
  canEditQty, qtyDraftOf, isQtyDraftDirty, isQtySaving, onQtyCellClick, onQtyDraftInput,
  onQtySave, onQtyEsc, onQtyBlur,
} = useFactoryTableRows(props, emit)
</script>

<style scoped lang="scss">
@use '@/styles/summary-tables.scss' as *;
@use '@/styles/summary-factory-rate-head.scss' as *;

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
  /* 落库状态提示绝对定位在本行右侧，故本行是定位锚点 */
  position: relative;
}
/* 提示位垂直居中锚定（水平/纵向定位由模板的 absolute right-0 top-1/2 给） */
.sm-loss-hint {
  transform: translateY(-50%);
}

/*
  损耗率表头「列名 + 统一损耗率输入同格」的排版与外观见
  `@/styles/summary-factory-rate-head.scss`（本 SFC 已接近 400 行门禁，故外置）。
*/

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
/* 名称格的「合计 N」副行 / 角色数量格的「（隐藏款）」标记：小字弱化，不抢主数据 */
.sm-sku-total-sub {
  margin-top: 2px;
  font-size: 12px;
  color: var(--color-text-muted);
}

/* 数量列：固定列宽，编辑态输入框 + 保存按钮不撑开列宽/行高 */
.sm-qty-col {
  width: 150px;
  min-width: 150px;
  white-space: nowrap;
}
.sm-qty-editor {
  display: inline-flex;
  align-items: stretch;
  gap: 4px;
  flex-wrap: nowrap;
}
/* 损耗率与数量输入共用同一尺寸（用户要求两者一致；高度由行内率输入决定，不额外撑高） */
.sm-inline-input {
  width: 56px;
  padding: 4px;
  font-family: inherit;
  font-size: 14px;
  line-height: normal;
  box-sizing: border-box;
}
.sm-qty-save {
  padding: 0 6px;
  font-size: 12px;
  line-height: normal;
  color: var(--color-primary-600);
  border: 1px solid var(--color-primary-500);
  border-radius: 6px;
  background: white;
  cursor: pointer;
  white-space: nowrap;
  box-sizing: border-box;
}
.sm-qty-save:hover {
  background: var(--color-primary-50);
}
.sm-qty-save:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.sm-qty-cell {
  cursor: text;
}
</style>
