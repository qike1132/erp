<template>
  <!-- 汇总列表单行：一行一单，仅订单级汇总字段；SKU 明细下沉到详情弹窗 -->
  <div
    :class="[
      'bo-grid bo-grid-row bo-row-clickable',
      { 'bo-row-highlight': highlightId !== null && String(item.id) === highlightId },
    ]"
    @click="openDetail(item)"
  >
    <div v-if="selectable" class="bo-td bo-td-center bo-td-select" style="width: 40px;" @click.stop>
      <UiCheckbox :checked="selected" :aria-label="`选择订单 ${item.order_no || item.id}`" @update:checked="$emit('toggleSelect', item)" />
    </div>

    <!-- 订单类型：订单/备货徽章（原订单号列删除，改展示类型） -->
    <div class="bo-td bo-td-center" style="width: 90px;">
      <span v-if="item.record_type === 'stockin'" class="bo-type-badge bo-type-badge--stockin">备货</span>
      <span v-else class="bo-type-badge bo-type-badge--order">订单</span>
    </div>

    <div class="bo-td bo-td-center bo-td-nowrap" style="width: 150px;">
      <span class="bo-cell-muted" :title="item.order_date || ''">{{ item.order_date || '-' }}</span>
    </div>

    <div class="bo-td bo-td-center bo-td-nowrap" style="width: 170px;">
      <span class="bo-customer" :title="item.customer || ''">{{ item.customer || '-' }}</span>
    </div>

    <div class="bo-td bo-td-center bo-td-nowrap" style="width: 100px;">
      <span class="bo-cell-main">{{ item.factories?.join(', ') || '湖北' }}</span>
    </div>

    <!-- SKU 数：多 SKU 订单用徽章提示，点击同样进入详情 -->
    <div class="bo-td bo-td-center" style="width: 90px;">
      <span class="bo-sku-count" :class="{ 'bo-sku-count--multi': skuCount > 1 }">{{ skuCount }} 项</span>
    </div>

    <!-- 订单数量：订单级汇总（rowTotalOrderQty 口径），来自采购单实际下单量时加粗 -->
    <div class="bo-td bo-td-center" style="width: 110px;">
      <span class="bo-qty" :class="{ 'bo-qty--ordered': item.is_ordered === true }">{{ totalOrderQty }}</span>
    </div>

    <!-- 生产数量：订单级汇总 = 订单数量 + 备品数量；不可派生显示「—」 -->
    <div class="bo-td bo-td-center" style="width: 110px;">
      <span v-if="totalProdQty !== null" class="bo-prod">{{ totalProdQty }}</span>
      <span v-else class="bo-prod bo-prod--none">—</span>
    </div>

    <!-- 小义开单 -->
    <div class="bo-td bo-td-center" style="width: 110px;">
      <span v-if="item.is_ordered === true" class="bo-open-badge bo-open-badge--done">已开单</span>
      <span
        v-else-if="item.confirmed === false"
        class="bo-open-badge bo-open-badge--pending"
        :title="NOT_ORDERED_TIP"
      >未开单</span>
      <span v-else class="bo-open-badge bo-open-badge--muted">未开单</span>
    </div>

    <!-- 确认状态列：未确认 TAB 下整列隐藏 -->
    <div v-if="confirmStatus !== 'unconfirmed'" class="bo-td bo-td-center" style="width: 110px;">
      <span v-if="item.confirmed" class="bo-confirm-badge bo-confirm-badge--done">已确认</span>
      <span v-else class="bo-confirm-badge bo-confirm-badge--pending">未确认</span>
    </div>

    <!-- 确认操作列：未确认记录显示确认按钮 -->
    <div v-if="confirmStatus !== 'confirmed'" class="bo-td bo-td-center" style="width: 130px;">
      <button
        v-if="!item.confirmed"
        class="bo-confirm-btn"
        :disabled="isConfirming || (item.confirmed === false && item.is_ordered === false)"
        :title="item.confirmed === false && item.is_ordered === false ? NOT_ORDERED_TOAST : ''"
        @click.stop="handleConfirm(item)"
      >
        {{ isConfirming ? '确认中…' : '确认订单' }}
      </button>
      <span v-else class="bo-confirm-badge bo-confirm-badge--done">已确认</span>
    </div>

    <!-- 备注：订单级，单行省略 -->
    <div class="bo-td bo-td-left bo-td-nowrap" style="width: 160px;">
      <span class="bo-cell-muted" :title="item.note || ''">{{ item.note || '-' }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * BeileOrderRow.vue — 湖北订单汇总列表单行（两级结构之一级）
 *
 * 一行一单，只承载订单级汇总字段：类型 / 下单时间 / 客户 / 工厂 /
 * SKU 数 / 订单数量 / 生产数量 / 小义开单 / 确认状态 / 确认操作 / 备注。
 * 逐 SKU 明细不再内嵌到列表行，而是点击整行进入详情弹窗（二级），
 * 从而彻底消除「20 个 SKU 挤在单行」的可读性问题。
 *
 * 数量口径（单一真源）：订单数量 = rowTotalOrderQty，生产数量 = rowTotalProductionQty，
 * 均为订单级汇总，与详情弹窗 / 导出 XLS / 打印预览同源（AC-12）。
 */
import { computed } from 'vue'
import {
  NOT_ORDERED_TIP,
  NOT_ORDERED_TOAST,
  rowTotalOrderQty,
  rowTotalProductionQty,
  type BeileOrderRow as BeileOrderRowType,
} from '@/views/beile-order/composables/useBeileOrders'
import UiCheckbox from '@/components/ui/UiCheckbox.vue'

const props = defineProps<{
  /** 当前订单行数据 */
  item: BeileOrderRowType
  /** 确认状态筛选：unconfirmed / confirmed */
  confirmStatus: string
  /** 当前行是否处于确认中（按钮禁用态依赖） */
  isConfirming: boolean
  /** 通知跳转高亮的订单 id（URL order_id） */
  highlightId: string | null
  /** 是否显示行选择复选框 */
  selectable: boolean
  /** 当前行是否被选中 */
  selected: boolean
}>()

const emit = defineEmits<{
  /** 行点击：打开订单详情 */
  open: [item: BeileOrderRowType]
  /** 确认订单 */
  confirm: [item: BeileOrderRowType]
  /** 切换行选中状态（携带整行：选中键 = record_type:id 复合，防订单/备货 id 撞号串扰） */
  toggleSelect: [item: BeileOrderRowType]
}>()

/** SKU 数量（订单级汇总事实） */
const skuCount = computed(() => (props.item.items || []).length)
/** 订单级「订单数量」汇总 */
const totalOrderQty = computed(() => rowTotalOrderQty(props.item))
/** 订单级「生产数量」汇总；未下单 → null */
const totalProdQty = computed(() => rowTotalProductionQty(props.item))

/** 行点击：交给父组件打开详情弹窗（300ms 防连点） */
let lastOpenAt = 0
function openDetail(item: BeileOrderRowType) {
  const now = Date.now()
  if (now - lastOpenAt < 300) return
  lastOpenAt = now
  emit('open', item)
}

/** 确认订单：交给父组件执行确认流程 */
function handleConfirm(item: BeileOrderRowType) {
  emit('confirm', item)
}
</script>

<style scoped>
/* 汇总列表行：flex 网格，列宽与表头一致 */
.bo-grid {
  display: flex;
  width: 100%;
  font-size: 13px;
}
.bo-td {
  box-sizing: border-box;
  flex: 0 0 auto;
  padding: 10px 14px;
  border-right: 1px solid #d8dce2;
  overflow: hidden;
  align-self: stretch;
  display: flex;
  align-items: center;
  justify-content: center;
}
.bo-td:last-child {
  flex: 1 1 auto;
  min-width: 160px;
  border-right: none;
}
.bo-td-left {
  justify-content: flex-start;
}
.bo-td-center {
  justify-content: center;
}
.bo-grid-row {
  height: 100%;
  align-items: center;
  border-bottom: 1px solid #d8dce2;
  color: var(--color-text);
  transition: background 0.2s ease;
}
.bo-grid-row:hover {
  background: var(--color-primary-50);
}
.bo-row-highlight {
  background: var(--color-warning-50) !important;
  box-shadow: inset 3px 0 0 var(--color-warning-500);
}
.bo-row-clickable {
  cursor: pointer;
}
.bo-td-select {
  padding: 10px 8px;
}
.bo-td-nowrap {
  white-space: nowrap;
}

/* 订单类型徽章列：点击整行打开详情，无需单独链接 */

/* SKU 数 */
/* SKU 数与「订单数量 / 生产数量」同处一行数字区，须同字号同形态。
   原实现为 12px + 胶囊（padding 1px 8px / 圆角 6px / 多 SKU 加浅蓝底），
   与相邻数字列的 13px 纯文本不一致 —— 胶囊底视觉上像一个多余的「标签图标」。
   统一为 13px 纯文本；多 SKU 曾以「蓝色 + 600 字重」强调，但同列内
   「4 项(蓝600) vs 1 项(灰400)」被判定为行间不一致 —— SKU 数本身已表达
   数量差异，无需再加视觉强调。全列统一灰 400（元数据弱于数量列正文）。
   .bo-sku-count--multi 类保留仅作语义/测试钩子，不再产生视觉差异。 */
.bo-sku-count {
  display: inline-flex;
  align-items: center;
  font-size: 13px;
  font-weight: 400;
  color: var(--color-text-muted, #64748b);
}

/* 数量：订单数量 / 生产数量同排数字统一取正文色，仅以字重区分 */
.bo-qty {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
/* 已下单的 700 字重强调已移除：同列内「已开单行 700 vs 未开单行 600」
   构成行间不一致，且行内「小义开单」徽章已表达同一信息。
   .bo-qty--ordered 类保留仅作语义/测试钩子，不再产生视觉差异。 */
.bo-prod {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.bo-prod--none {
  font-weight: 400;
  color: var(--color-text-muted);
}

/* 文本 */
.bo-customer {
  font-weight: 600;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
}
.bo-cell-main {
  font-weight: 600;
  color: var(--color-text);
}
.bo-cell-muted {
  color: var(--color-text-muted);
  font-size: 12px;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 徽章 / 按钮（沿用既有体系） */
.bo-type-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 700;
  border-radius: 5px;
  line-height: 1.5;
}
/* 与 .bo-open-badge--done / .bo-confirm-badge--done 统一取 success-700：
   三者底色同为 success-50，文字色必须同档，否则同一浅绿底上并存两种绿
   （success-600 #1e9e55 为青绿、success-700 #2e7d32 为黄绿，色相不同）。
   另：success-600 在 success-50 上对比度仅 3.2:1，低于 WCAG AA 4.5:1。 */
.bo-type-badge--order {
  background: var(--color-success-50, #e8f9ef);
  color: var(--color-success-700, #2e7d32);
}
.bo-type-badge--stockin {
  background: var(--color-primary-50, #eff5ff);
  color: var(--color-primary-600, #3a6bd6);
}
.bo-open-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 3px 10px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}
.bo-open-badge--done {
  background: var(--color-success-50);
  color: var(--color-success-700);
}
.bo-open-badge--pending {
  background: var(--color-warning-50);
  color: var(--color-warning-600);
}
.bo-open-badge--muted {
  background: var(--color-surface, #f4f6fc);
  color: var(--color-text-secondary);
}
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
.bo-confirm-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 3px 12px;
  font-size: 12px;
  font-weight: 600;
  border: 1px solid var(--color-primary-500);
  border-radius: 8px;
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  cursor: pointer;
  white-space: nowrap;
  font-family: inherit;
  transition: background 0.2s ease;
}
.bo-confirm-btn:hover:not(:disabled) {
  background: var(--color-primary-100);
}
.bo-confirm-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
