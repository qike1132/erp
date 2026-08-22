<template>
  <div
    :class="['bo-grid bo-grid-row bo-row-clickable', { 'bo-row-highlight': highlightId !== null && String(item.id) === highlightId, 'bo-row-multi-sku': (item.items?.length || 1) > 1 }]"
    @click="openDetail(item)"
  >
    <div v-if="selectable" class="bo-td bo-td-center bo-td-middle bo-td-select" style="width: 40px;" @click.stop>
      <UiCheckbox :checked="selected" @update:checked="$emit('toggleSelect', item.id)" />
    </div>
    <div class="bo-td bo-td-center bo-td-middle bo-td-nowrap" style="width: 90px;">
      <span v-if="item.record_type === 'stockin'" class="bo-type-badge bo-type-badge--stockin">备货</span>
      <span v-else class="bo-type-badge bo-type-badge--order">订单</span>
    </div>
    <div class="bo-td bo-td-center bo-td-middle bo-td-nowrap" style="width: 170px;">
      <span class="bo-order-date" :title="item.order_date || ''">{{ item.order_date || '-' }}</span>
    </div>
    <div class="bo-td bo-td-center bo-td-middle bo-customer-cell" style="width:170px">{{ item.customer || '-' }}</div>
    <div v-if="showProductColumn" class="bo-td bo-td-center bo-product-cell" style="width: 180px;">
      <template v-if="visibleSkus.length > 0">
        <div v-for="sku in visibleSkus" :key="sku.id" class="bo-sku-line">
          <span class="bo-sku-name" :title="sku.product_name || ''">{{ sku.product_name || '-' }}</span>
        </div>
      </template>
      <span v-else class="bo-sku-name">{{ item.product_name || '-' }}</span>
    </div>
    <div class="bo-td bo-td-center bo-td-middle" style="width: 100px;"><span class="bo-cell-main">{{ item.factories?.join(', ') || '湖北' }}</span></div>
    <div class="bo-td bo-td-center bo-td-middle" style="width: 130px;">
      <template v-if="showProductColumn && visibleSkus.length > 0">
        <strong>{{ visibleSkus.reduce((sum, s) => sum + (s.quantity || 0), 0) }}</strong>
      </template>
      <template v-else-if="item.items && item.items.length > 0">
        <strong>{{ item.items.reduce((sum, s) => sum + (s.quantity || 0), 0) }}</strong>
      </template>
      <template v-else><strong>{{ item.quantity }}</strong></template>
    </div>
    <!-- 确认状态列：订单与备货均参与确认流程；未确认 TAB 下整列隐藏（冗余） -->
    <div v-if="confirmStatus !== 'unconfirmed'" class="bo-td bo-td-center bo-td-middle" style="width: 110px;">
      <span v-if="item.confirmed" class="bo-confirm-badge bo-confirm-badge--done">已确认</span>
      <span v-else class="bo-confirm-badge bo-confirm-badge--pending">未确认</span>
    </div>
    <!-- 确认操作列：未确认记录显示确认按钮，已确认记录显示已确认徽章（已确认 TAB 隐藏整列） -->
    <div v-if="confirmStatus !== 'confirmed'" class="bo-td bo-td-center bo-td-middle" style="width: 130px;">
      <button
        v-if="!item.confirmed"
        class="bo-confirm-btn"
        :disabled="isConfirming"
        @click.stop="handleConfirm(item)"
      >
        {{ isConfirming ? '确认中…' : '确认订单' }}
      </button>
      <span v-else class="bo-confirm-badge bo-confirm-badge--done">已确认</span>
    </div>
    <div class="bo-td bo-td-left bo-td-middle" style="width: 160px;">
      <template v-if="visibleSkus.length > 0">
        <div v-for="sku in visibleSkus" :key="sku.id" class="bo-sku-line">
          <span v-if="sku.note" class="bo-sku-note" :title="sku.note">{{ sku.note }}</span>
        </div>
      </template>
      <span v-if="item.note" class="bo-sku-note">{{ item.note }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * BeileOrderRow.vue — 湖北订单虚拟列表单行
 *
 * 从 BeileOrderTab.vue 拆出的列表行：展示下单时间/客户/产品/数量/
 * 确认状态/确认操作/备注。行点击与确认按钮通过 emit 交回父组件处理。
 */
import { computed } from 'vue'
import type { BeileOrderRow as BeileOrderRowType } from '@/views/beile-order/composables/useBeileOrders'
import UiCheckbox from '@/components/ui/UiCheckbox.vue'

const props = defineProps<{
  /** 当前行数据 */
  item: BeileOrderRowType
  /** 是否显示产品名称列（已应用产品关键字筛选时） */
  showProductColumn: boolean
  /** 确认状态筛选：unconfirmed / confirmed */
  confirmStatus: string
  /** 当前行是否处于确认中（按钮禁用态依赖） */
  isConfirming: boolean
  /** 通知跳转高亮的订单 id（URL order_id） */
  highlightId: string | null
  /** 已应用的产品关键字（行内 SKU 过滤用） */
  keyword: string
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
  /** 切换行选中状态 */
  toggleSelect: [id: number]
}>()

/** SKU 是否匹配关键字（产品名称或条码） */
function skuMatchesKeyword(sku: { product_name?: string | null; product_barcode?: string | null }, kw: string): boolean {
  return (sku.product_name || '').toLowerCase().includes(kw)
    || (sku.product_barcode || '').toLowerCase().includes(kw)
}

/**
 * 行内展示的 SKU：应用产品筛选时仅返回名称/条码匹配关键字的 SKU，
 * 使产品名称、数量、备注只对应搜索到的那个产品；未筛选时返回全部。
 * 缓存为 computed，避免模板内多次调用重复计算。
 */
const visibleSkus = computed<NonNullable<BeileOrderRowType['items']>>(() => {
  const kw = props.keyword.trim().toLowerCase()
  const items = props.item.items || []
  if (!kw) return items
  const matched = items.filter((s) => skuMatchesKeyword(s, kw))
  return matched.length > 0 ? matched : items
})

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
/* 虚拟滚动表格行：flex 网格布局，列宽与表头一致 */
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
  flex-direction: column;
  justify-content: center;
}
.bo-td:last-child {
  flex: 1 1 auto;
  min-width: 160px;
  border-right: none;
}
.bo-td-left {
  text-align: left !important;
  align-items: flex-start;
}
.bo-td-center {
  text-align: center !important;
  align-items: center;
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
.bo-grid-row.bo-row-multi-sku {
  align-items: flex-start;
}
.bo-grid-row.bo-row-multi-sku .bo-td {
  justify-content: flex-start;
}
/* 通知跳转高亮行 */
.bo-row-highlight {
  background: var(--color-warning-50) !important;
  box-shadow: inset 3px 0 0 var(--color-warning-500);
}
.bo-customer-cell {
  font-weight: 600;
  white-space: nowrap;
}
.bo-product-cell {
  text-align: left !important;
  align-items: flex-start;
}
.bo-product-cell .bo-sku-name {
  display: block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.bo-cell-main {
  font-weight: 600;
  color: var(--color-text);
}
.bo-cell-muted {
  color: var(--color-text-muted);
  font-size: 12px;
}
.bo-td-middle {
  vertical-align: middle !important;
}
.bo-td-nowrap {
  white-space: nowrap;
}
.bo-td-select {
  padding: 10px 8px;
}
/* 下单时间列：标签 + 日期（对齐 purchase） */
.bo-order-meta-cell {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}
.bo-order-date {
  flex-shrink: 0;
}
.bo-type-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 1px 6px;
  font-size: 10px;
  font-weight: 700;
  border-radius: 4px;
  line-height: 1.5;
}
.bo-type-badge--order {
  background: var(--color-success-50, #e8f9ef);
  color: var(--color-success-600, #1e9e55);
}
.bo-type-badge--stockin {
  background: var(--color-primary-50, #eff6ff);
  color: var(--color-primary-600, #2563eb);
}
.bo-sku-line {
  padding: 2px 0;
  font-size: 13px;
  line-height: 1.4;
}
.bo-sku-name {
  font-weight: 500;
  color: var(--color-text);
  display: inline-block;
}
/* 备注（对齐 customer-order 详情 SKU 备注样式） */
.bo-sku-note {
  display: inline-block;
  color: var(--color-text-secondary);
  font-size: 12px;
  word-break: break-word;
  vertical-align: middle;
}
/* 确认状态（湖北订单确认流程） */
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
  transition: background 0.2s ease;
}
.bo-confirm-btn:hover:not(:disabled) {
  background: var(--color-primary-100);
}
.bo-confirm-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.bo-row-clickable {
  cursor: pointer;
}
</style>
