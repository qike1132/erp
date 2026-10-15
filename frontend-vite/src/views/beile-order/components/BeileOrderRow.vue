<template>
  <!-- 汇总列表订单块：一行一 SKU，订单级列跨行合并（对齐 /report 订单流水的多 SKU 效果） -->
  <div
    :class="[
      'bo-block',
      { 'bo-row-highlight': highlightId !== null && String(item.id) === highlightId },
    ]"
    :style="blockStyle"
  >
    <!-- 订单级列：grid-row 跨 span 行（等效 rowspan），首行起排 -->
    <div
      v-for="col in orderCols"
      :key="`o-${col.key}`"
      class="bo-td"
      :class="[`bo-td-${col.align}`, { 'bo-td-order-no': col.key === 'orderNo', 'bo-td-select': col.key === 'select', 'bo-td-nowrap': col.key !== 'note' }]"
      :style="cellStyle(col.key, 1, span)"
    >
      <!-- 行选择 -->
      <UiCheckbox
        v-if="col.key === 'select'"
        :checked="selected"
        :aria-label="`选择订单 ${item.order_no || item.id}`"
        @click.stop
        @update:checked="$emit('toggleSelect', item)"
      />

      <!-- 订单类型：订单/备货徽章 -->
      <template v-else-if="col.key === 'type'">
        <span v-if="item.record_type === 'stockin'" class="bo-type-badge bo-type-badge--stockin">备货</span>
        <span v-else class="bo-type-badge bo-type-badge--order">订单</span>
      </template>

      <!-- 订单号 -->
      <span v-else-if="col.key === 'orderNo'" class="bo-order-no" :title="item.order_no || ''">{{ item.order_no || '-' }}</span>

      <span v-else-if="col.key === 'date'" class="bo-date" :title="item.order_date || ''">{{ item.order_date || '-' }}</span>

      <span v-else-if="col.key === 'customer'" class="bo-customer" :title="item.customer || ''">{{ item.customer || '-' }}</span>

      <span v-else-if="col.key === 'factory'" class="bo-cell-main">{{ item.factories?.join(', ') || '湖北' }}</span>

      <!-- 小义开单 -->
      <template v-else-if="col.key === 'opened'">
        <span v-if="item.is_ordered === true" class="bo-open-badge bo-open-badge--done">已开单</span>
        <span
          v-else-if="item.confirmed === false"
          class="bo-open-badge bo-open-badge--pending"
          :title="NOT_ORDERED_TIP"
        >未开单</span>
        <span v-else class="bo-open-badge bo-open-badge--muted">未开单</span>
      </template>

      <!-- 确认状态 -->
      <template v-else-if="col.key === 'confirmStatus'">
        <span v-if="item.confirmed" class="bo-confirm-badge bo-confirm-badge--done">已确认</span>
        <span v-else class="bo-confirm-badge bo-confirm-badge--pending">未确认</span>
      </template>

      <!-- 确认操作 -->
      <button
        v-else-if="col.key === 'confirmAction' && confirmable && !item.confirmed"
        class="bo-confirm-btn"
        :disabled="isConfirming || (item.confirmed === false && item.is_ordered === false)"
        :title="item.confirmed === false && item.is_ordered === false ? NOT_ORDERED_TOAST : ''"
        @click.stop="handleConfirm(item)"
      >
        {{ isConfirming ? '确认中…' : '确认订单' }}
      </button>
      <span v-else-if="col.key === 'confirmAction'" class="bo-confirm-badge bo-confirm-badge--done">已确认</span>

      <!-- 备注 -->
      <span v-else-if="col.key === 'note'" class="bo-note" :title="item.note || ''">{{ item.note || '-' }}</span>
    </div>

    <!-- SKU 列：逐 SKU 一行（产品名称/订单数量/生产数量） -->
    <template v-for="(sku, si) in skus" :key="sku.id ?? si">
      <div
        v-for="col in skuCols"
        :key="`s-${si}-${col.key}`"
        class="bo-td"
        :class="[`bo-td-${col.align}`, 'bo-td-nowrap']"
        :style="cellStyle(col.key, si + 1, 1)"
      >
        <span
          v-if="col.key === 'productName'"
          class="bo-sku-name"
          :title="sku.product_name || ''"
        >{{ sku.product_name || '-' }}</span>
        <span
          v-else-if="col.key === 'orderQty'"
          class="bo-qty"
          :class="{ 'bo-qty--ordered': skuIsOrdered(item, sku) }"
        >{{ skuOrderQty(item, sku) }}</span>
        <span
          v-else-if="col.key === 'prodQty'"
          class="bo-prod"
          :class="{ 'bo-prod--none': skuProductionQty(item, sku) === null }"
        >{{ skuProductionQty(item, sku) ?? '—' }}</span>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
/**
 * BeileOrderRow.vue — 湖北订单汇总列表「订单块」（两级结构之一级）
 *
 * 2026-10-15 多 SKU 改版（对齐 /report 订单流水方案 C）：
 * 一行一 SKU，订单级列跨 span 行合并（CSS Grid，等效 rowspan），SKU 列
 * （产品名称/订单数量/生产数量）逐行渲染。
 * 列序/列宽与布局/数量口径统一走 useBeileOrderBlock（与表头、导出/打印同源，AC-12）。
 */
import {
  NOT_ORDERED_TIP,
  NOT_ORDERED_TOAST,
  useBeileOrderBlock,
  skuIsOrdered,
  skuOrderQty,
  skuProductionQty,
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
  /** 是否显示确认按钮（beile_order_confirm 权限门控） */
  confirmable: boolean
  /** 是否显示行选择复选框 */
  selectable: boolean
  /** 当前行是否被选中 */
  selected: boolean
  /** 已应用的产品关键字：仅渲染命中 SKU（与导出/打印 filterVisibleSkus 同源） */
  keyword?: string
}>()

const emit = defineEmits<{
  /** 确认订单 */
  confirm: [item: BeileOrderRowType]
  /** 切换行选中状态（携带整行：选中键 = record_type:id 复合，防订单/备货 id 撞号串扰） */
  toggleSelect: [item: BeileOrderRowType]
}>()

// 布局与数量口径统一走 composable（组件 ≤400 行门禁；口径单一真源 AC-12）
const {
  orderCols,
  skuCols,
  blockStyle,
  cellStyle,
  skus,
  span,
} = useBeileOrderBlock(props)

/** 确认订单：交给父组件执行确认流程 */
function handleConfirm(item: BeileOrderRowType) {
  emit('confirm', item)
}
</script>

<style scoped>
/* 订单块：CSS Grid，列模板与表头同源（beileGridTemplate） */
.bo-block {
  display: grid;
  width: 100%;
  font-size: 13px;
  color: var(--color-text);
}
.bo-td {
  box-sizing: border-box;
  padding: 6px 14px;
  border-right: 1px solid #d8dce2;
  border-bottom: 1px solid #d8dce2;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}
.bo-td-left {
  justify-content: flex-start;
}
.bo-td-center {
  justify-content: center;
}
.bo-td-select {
  padding: 6px 8px;
}
.bo-row-highlight {
  background: var(--color-warning-50) !important;
  box-shadow: inset 3px 0 0 var(--color-warning-500);
}
.bo-td-nowrap {
  white-space: nowrap;
}

/* SKU 逐行：产品名称 */
.bo-customer {
  font-weight: 600;
  color: var(--color-text);
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
}
.bo-sku-name {
  font-weight: 500;
  color: var(--color-text);
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 数量：订单数量 / 生产数量同排数字统一取正文色，仅以字重区分 */
/* .bo-qty--ordered 仅作语义/测试钩子，不再产生视觉差异（行间一致性裁决） */
.bo-qty,
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
.bo-cell-main {
  font-weight: 600;
  color: var(--color-text);
}
/* 下单时间 / 备注：字号与颜色对齐 /outsource（日期正文 13px 正文色、备注 12px text-secondary） */
.bo-date {
  font-size: 13px;
  color: var(--color-text);
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
}
.bo-note {
  color: var(--color-text-secondary);
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
  font-size: 10px;
  font-weight: 700;
  border-radius: 5px;
  line-height: 1.5;
}
.bo-type-badge--order {
  background: var(--color-success-50, #e8f9ef);
  color: var(--color-success-600, #1e9e55);
}
.bo-type-badge--stockin {
  background: var(--color-primary-50, #eff5ff);
  color: var(--color-primary-600, #3a6bd6);
}
/* 订单号：等宽字体便于逐位比对（单号是给人念/抄的） */
.bo-order-no {
  font-family: Consolas, ui-monospace, monospace;
  font-size: 12px;
  color: var(--color-text);
  letter-spacing: 0.2px;
}
/* 状态徽章（小义开单 / 确认状态 / 确认操作 fallback）共用同一形态 */
.bo-open-badge,
.bo-confirm-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 3px 10px;
  border-radius: 8px;
  font-size: 11.5px;
  font-weight: 600;
  white-space: nowrap;
}
.bo-open-badge--done,
.bo-confirm-badge--done {
  background: var(--color-success-50);
  color: var(--color-success-700);
}
.bo-open-badge--pending,
.bo-confirm-badge--pending {
  background: var(--color-warning-50);
  color: var(--color-warning-600);
}
.bo-open-badge--muted {
  background: var(--color-surface, #f4f6fc);
  color: var(--color-text-secondary);
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
