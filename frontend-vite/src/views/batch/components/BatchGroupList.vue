<template>
  <div class="bt-groups">
    <div v-for="group in grouped" :key="group.customer" class="bt-group-card">
      <div class="bt-group-header">
        <span class="bt-group-name">{{ group.customer }}</span>
        <span class="bt-group-count">{{ group.products.length }} 个产品</span>
      </div>
      <div v-for="prod in group.products" :key="prod.key" class="bt-product-row">
        <div class="bt-product-info">
          <span class="bt-product-name">{{ prod.productName || '' }}</span>
          <span class="bt-product-barcode">{{ prod.productBarcode || '' }}</span>
        </div>
        <div class="bt-order-chips">
          <div
            v-for="order in prod.orders"
            :key="(order.record_type || 'order') + '-' + order.id"
            class="bt-chip"
            :class="[chipStatusClass(order), order.record_type === 'stockin' && 'bt-chip--stockin']"
          >
            <span class="bt-chip-date">{{ formatDate(order.order_date) }}</span>
            <span class="bt-chip-qty">{{ order.quantity }}</span>
            <template v-if="order.record_type !== 'stockin'">
              <input
                class="bt-batch-input"
                :class="{ 'bt-batch-input--has-value': order.batch_no }"
                :value="editingId === order.id ? editingValue : (order.batch_no ?? '')"
                :placeholder="editingId === order.id ? '批次号' : '批次号'"
                @focus="startEdit(order)"
                @input="onBatchInput($event, order)"
                @keydown.enter.prevent="saveBatchNo(order)"
                @keydown.escape="cancelEdit"
                @blur="saveBatchNo(order)"
              />
              <button
                v-if="order.batch_no"
                class="bt-complete-btn"
                @click.stop="openCompleteConfirm(order)"
              >完成</button>
            </template>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * BatchGroupList.vue — 批次客户分组列表
 *
 * 从 BatchView.vue 拆出：按客户 → 产品分组展示订单/备货记录 chips，
 * 支持内联编辑批次号（enter/blur 保存、escape 取消）与完成批次入口。
 */
import { ref } from 'vue'
import { orderBatchApi } from '@/api'
import type { BatchQueryItem } from '@/types'
import { showToast } from '@/composables/useToast'
import { formatDate } from '@/utils/format'
import type { CustomerGroup } from '@/views/batch/composables/useBatchQuery'

defineProps<{
  /** 客户 → 产品 → 订单 分组数据 */
  grouped: CustomerGroup[]
}>()

const emit = defineEmits<{
  /** 批次号保存成功后刷新主列表 */
  refresh: []
  /** 点击「完成」按钮，请求父组件打开完成确认弹窗 */
  requestComplete: [order: BatchQueryItem]
}>()

/** 根据订单状态返回对应的 chip CSS 类名 */
function chipStatusClass(order: BatchQueryItem): string {
  const s = order.status
  if (!s) return ''
  if (s === '已出货' || s === '批次已完成') return 'bt-chip--completed'
  if (s === '已备货') return 'bt-chip--stocked'
  if (s === '部分备货') return 'bt-chip--partial'
  if (s === '待出货') return 'bt-chip--shipping'
  if (s === '待备货') return 'bt-chip--pending'
  return ''
}

// ---- Batch number inline editing ----
const editingId = ref<number | null>(null)
const editingValue = ref('')
const editingOriginal = ref('')
const saving = ref(false)

/** 开始编辑某订单的批次号 */
function startEdit(order: BatchQueryItem) {
  editingId.value = order.id
  editingValue.value = order.batch_no ?? ''
  editingOriginal.value = order.batch_no ?? ''
}

function onBatchInput(event: Event, order: BatchQueryItem) {
  if (editingId.value !== order.id) {
    editingId.value = order.id
    editingOriginal.value = order.batch_no ?? ''
  }
  editingValue.value = (event.target as HTMLInputElement).value
}

function cancelEdit() {
  editingId.value = null
  editingValue.value = ''
}

/** 保存批次号到后端，仅在值实际变化时提交 */
async function saveBatchNo(order: BatchQueryItem) {
  if (saving.value) return
  const newValue = editingValue.value.trim()
  // Only save if value actually changed from the original
  if (newValue === editingOriginal.value) {
    editingId.value = null
    return
  }
  if (!newValue) {
    editingId.value = null
    return
  }
  saving.value = true
  try {
    await orderBatchApi.updateBatchNo(order.id, { batch_no: newValue || null })
    showToast('批次号已更新', 'success')
    editingId.value = null
    emit('refresh')
  } catch {
    showToast('批次号更新失败', 'error')
  } finally {
    saving.value = false
  }
}

/** 点击完成：交给父组件打开完成确认弹窗 */
function openCompleteConfirm(order: BatchQueryItem) {
  emit('requestComplete', order)
}
</script>

<style scoped>
/* ===== 客户分组卡片 ===== */
.bt-groups {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 0 24px 16px;
  overflow-y: auto;
  flex: 1;
  min-width: 0;
}

.bt-group-card {
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 12px;
  transition: background 0.3s ease, border-color 0.3s ease, box-shadow 0.3s ease;
  min-width: 0;
  overflow: hidden;
}
.bt-group-card:hover {
  border-color: var(--color-primary-500);
  background: var(--color-primary-50);
  box-shadow: 0 2px 8px rgba(91, 141, 239, 0.15);
}

.bt-group-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
}
.bt-group-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
}
.bt-group-count {
  font-size: 12px;
  color: var(--color-text-secondary);
}

/* ===== 产品行 ===== */
.bt-product-row {
  display: flex;
  align-items: flex-start;
  padding: 12px 16px;
  gap: 16px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  transition: background 0.3s ease, transform 0.3s ease;
  min-width: 0;
  overflow: hidden;
}
.bt-product-row:last-child {
  border-bottom: none;
}
.bt-product-row:hover {
  background: var(--color-primary-50);
  transform: translateX(4px);
}

.bt-product-info {
  flex-shrink: 0;
  width: 160px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 2px;
  padding-top: 22px;
}
.bt-product-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
}
.bt-product-barcode {
  font-size: 12px;
  font-family: var(--font-mono);
  color: var(--color-text-muted);
}

/* ===== 订单 Chips (Section 13 列表项风格) ===== */
.bt-order-chips {
  /* CSS 变量驱动的滚动条 — 通过父级 :hover/:active 切换 */
  --sb-color: rgba(91, 141, 239, 0.55);
  --sb-color-hover: rgba(91, 141, 239, 0.85);
  --sb-color-active: rgba(91, 141, 239, 1);
  --sb-track: rgba(91, 141, 239, 0.08);
  --sb-track-hover: rgba(91, 141, 239, 0.14);
  --sb-height: 10px;

  display: flex;
  flex-wrap: nowrap;
  gap: 8px;
  flex: 1;
  min-width: 0;
  overflow-x: auto;
  overflow-y: hidden;
  padding: 6px 4px 12px;
  scroll-behavior: smooth;
  -webkit-overflow-scrolling: touch;
  scrollbar-gutter: stable;
  /* Firefox */
  scrollbar-width: thin;
  scrollbar-color: var(--sb-color) transparent;
}
/* 三态：默认 → hover → active（通过父元素状态触发） */
.bt-order-chips:hover {
  --sb-color: var(--sb-color-hover);
  --sb-track: var(--sb-track-hover);
}
.bt-order-chips:active {
  --sb-color: var(--sb-color-active);
}

/* Webkit 滚动条 */
.bt-order-chips::-webkit-scrollbar {
  height: var(--sb-height);
}
.bt-order-chips::-webkit-scrollbar-track {
  background: var(--sb-track);
  border-radius: 9999px;
  margin: 0 4px;
  transition: background 0.25s ease;
}
.bt-order-chips::-webkit-scrollbar-thumb {
  background: var(--sb-color);
  border-radius: 9999px;
  min-height: var(--sb-height);
  transition: background 0.25s ease;
}

.bt-chip {
  display: inline-flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 6px 10px;
  border-radius: 10px;
  font-size: 13px;
  background: white;
  border: 2px solid var(--color-border-light, #e2e8f0);
  transition: background 0.3s ease, border-color 0.3s ease, box-shadow 0.3s ease;
  white-space: nowrap;
}
.bt-chip:hover {
  border-color: var(--color-primary-500);
  background: var(--color-primary-50);
  box-shadow: 0 2px 8px rgba(91, 141, 239, 0.15);
}

/* Chip 状态色 (Section 17 Status Badge) */
.bt-chip--pending {
  border-color: var(--color-border-light, #e2e8f0);
}
.bt-chip--partial {
  border-color: var(--color-info-200);
  background: var(--color-info-50);
}
.bt-chip--stocked {
  border-color: var(--color-primary-200);
  background: var(--color-primary-50);
}
.bt-chip--shipping {
  border-color: var(--color-purple-200);
  background: var(--color-purple-50);
}
.bt-chip--completed {
  border-color: var(--color-success-200);
  background: var(--color-success-50);
}
.bt-chip--stockin {
  border-color: #93c5fd;
  background: #eff6ff;
}

.bt-chip-date {
  font-size: 12px;
  color: var(--color-text-secondary);
}
.bt-chip-qty {
  font-size: 16px;
  font-weight: 700;
  color: var(--color-text);
  line-height: 1.3;
}

/* ===== 批次号输入 ===== */
.bt-batch-input {
  width: 120px;
  padding: 2px 8px;
  font-size: 12px;
  color: var(--color-heading);
  background: white;
  border: 1px dashed var(--color-border, #d1d5db);
  border-radius: 6px;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
  outline: none;
  font-family: inherit;
  box-sizing: border-box;
}
.bt-batch-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.bt-batch-input::placeholder {
  color: var(--color-text-muted);
  font-size: 11px;
}
.bt-batch-input:focus {
  border-color: var(--color-primary-400);
  border-style: solid;
  box-shadow: 0 0 0 2px rgba(91, 141, 239, 0.15);
}
.bt-batch-input--has-value {
  border-style: solid;
  border-color: var(--color-primary-200);
  color: var(--color-primary-700);
  font-weight: 600;
}

/* ===== 完成批次按钮 ===== */
.bt-complete-btn {
  padding: 1px 8px;
  font-size: 11px;
  font-weight: 600;
  color: var(--color-success-600, #16a34a);
  background: var(--color-success-50, #f0fdf4);
  border: 1px solid var(--color-success-200, #bbf7d0);
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.2s ease, border-color 0.2s ease, transform 0.2s ease;
  font-family: inherit;
  white-space: nowrap;
}
.bt-complete-btn:hover {
  background: var(--color-success-100, #dcfce7);
  border-color: var(--color-success-400, #4ade80);
  transform: translateY(-1px);
}

/* ===== 响应式 ===== */
@media (max-width: 768px) {
  .bt-product-row {
    flex-direction: column;
    gap: 8px;
  }
  .bt-product-info {
    width: auto;
  }
  .bt-groups {
    padding: 0 16px 12px;
  }
}
</style>
