<template>
  <div class="bt-container">
    <div class="page-card page-card-main">

      <!-- 卡片头部 -->
      <div class="page-card-header">
        <HeaderTabs />
        <div class="bt-header-search">
          <UiInput v-model="filters.keyword" placeholder="搜索" style="width: 160px" />
          <UiButton variant="primary" @click="refetch()"> 查询 </UiButton>
        </div>
        <div class="bt-header-actions">
          <span v-if="whitelistCustomers.length" class="bt-tab-group" role="tablist">
            <button
              v-for="c in whitelistCustomers"
              :key="c"
              role="tab"
              :aria-selected="filters.customer === c"
              class="bt-tab-btn"
              :class="{ 'bt-tab-btn--active': filters.customer === c }"
              @click="switchCustomer(c)"
            >{{ c }}</button>
          </span>

          <button class="bt-whitelist-btn" @click="showWhitelistModal = true" aria-label="设置">
            <i class="fas fa-cog"  aria-hidden="true" />
          </button>
          <!-- 白名单设置弹窗 -->
          <div v-if="showWhitelistModal" class="bt-whitelist-overlay" @click.self="showWhitelistModal = false">
            <div class="bt-whitelist-modal">
              <div class="bt-whitelist-header">
                <span>白名单客户</span>
                <button class="bt-whitelist-close" @click="showWhitelistModal = false">&times;</button>
              </div>
              <div class="bt-whitelist-body">
                <label v-for="c in allCustomers" :key="c" class="bt-whitelist-item">
                  <input type="checkbox" :value="c" v-model="whitelistEdit" />
                  <span>{{ c }}</span>
                </label>
              </div>
              <div class="bt-whitelist-footer">
                <UiButton variant="outline" @click="showWhitelistModal = false">取消</UiButton>
                <UiButton variant="primary" @click="saveWhitelist" :disabled="whitelistSaving">保存</UiButton>
              </div>
            </div>
          </div>
          <!-- 完成批次确认弹窗 -->
          <div v-if="showCompleteModal" class="bt-whitelist-overlay" @click.self="showCompleteModal = false">
            <div class="bt-whitelist-modal">
              <div class="bt-whitelist-header">
                <span>确认完成批次</span>
                <button class="bt-whitelist-close" @click="showCompleteModal = false">&times;</button>
              </div>
              <div class="bt-whitelist-body" style="padding: 20px; font-size: 14px; color: var(--color-text);">
                确定要完成批次 <strong>{{ completingBatchNo }}</strong> 吗？完成后该批次将不再显示。
              </div>
              <div class="bt-whitelist-footer">
                <UiButton variant="outline" @click="showCompleteModal = false">取消</UiButton>
                <UiButton variant="primary" :disabled="completing" @click="confirmComplete">确定</UiButton>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 主内容 -->
      <div class="page-card-main">
        <div v-if="isLoading && !result" class="bt-loading">
          <UiSpinner />
        </div>
        <template v-else>
          <div v-if="isFetching" class="bt-fetching-bar"><div class="bt-fetching-progress" /></div>

          <!-- 客户分组卡片 -->
          <div v-if="grouped.length" class="bt-groups">
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
          <div v-else class="bt-empty">
            <i class="fas fa-inbox"  aria-hidden="true" />
            <span>暂无批次数据</span>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * BatchView.vue — 批次管理页面
 *
 * 职责：
 * - 按客户白名单分组展示订单/备货记录
 * - 支持内联编辑批次号、完成批次操作
 * - 支持白名单客户的增删管理
 */
import { ref, reactive, computed, watch } from 'vue'
import { useQuery, keepPreviousData } from '@tanstack/vue-query'
import { batchApi, orderBatchApi, customerApi } from '@/api'
import type { BatchQueryItem } from '@/types'
import HeaderTabs from '@/layouts/components/HeaderTabs.vue'
import UiInput from '@/components/ui/UiInput.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'

import { showToast } from '@/composables/useToast'
import { formatDate } from '@/utils/format'

const perPage = ref(500)

const filters = reactive({ batch_no: '', customer: '', status: '', keyword: '' })

// ---- Whitelist customers ----
const { data: whitelistData, refetch: refetchWhitelist } = useQuery({
  queryKey: ['order-batch-whitelist'],
  queryFn: () => orderBatchApi.whitelist(),
  staleTime: 300_000,
})
const whitelistCustomers = computed<string[]>(() => whitelistData.value?.customers ?? [])

// Auto-select first whitelist customer
watch(whitelistCustomers, (list) => {
  if (list.length && (!filters.customer || !list.includes(filters.customer))) {
    filters.customer = list[0]!
  }
}, { immediate: true })

// ---- Whitelist modal ----
const showWhitelistModal = ref(false)
const whitelistEdit = ref<string[]>([])
const whitelistSaving = ref(false)

// Fetch all active customers from customer management API
const { data: activeNamesData } = useQuery({
  queryKey: ['customer-active-names'],
  queryFn: () => customerApi.activeNames(),
  staleTime: 300_000,
})
const allCustomers = computed<string[]>(() =>
  (activeNamesData.value ?? []).map((c: { name: string }) => c.name)
)

// When modal opens, populate edit list from current whitelist
watch(showWhitelistModal, (val) => {
  if (val) {
    whitelistEdit.value = [...whitelistCustomers.value]
  }
})

/** 保存白名单客户列表 */
async function saveWhitelist() {
  whitelistSaving.value = true
  try {
    await orderBatchApi.setWhitelist(whitelistEdit.value)
    showToast('白名单已更新', 'success')
    showWhitelistModal.value = false
    await refetchWhitelist()
    refetch()
  } catch {
    showToast('白名单更新失败', 'error')
  } finally {
    whitelistSaving.value = false
  }
}

/** 切换客户筛选并重新查询 */
function switchCustomer(customer: string) {
  filters.customer = customer
  refetch()
}

// ---- Status options ----


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

// ---- Main data query ----
const {
  data: result,
  isLoading,
  isFetching,
  refetch,
} = useQuery({
  queryKey: ['batch-query', perPage, filters],
  queryFn: async () => {
    const params: Record<string, unknown> = { per_page: perPage.value }
    if (filters.batch_no) params.batch_no = filters.batch_no
    if (filters.customer) params.customer = filters.customer
    if (filters.status) params.status = filters.status
    if (filters.keyword) params.keyword = filters.keyword
    return await batchApi.list(params)
  },
  staleTime: 30_000,
  placeholderData: keepPreviousData,
})

const items = computed<BatchQueryItem[]>(() => result.value?.data ?? [])

// ---- Grouped data: customer → product → orders ----
interface ProductGroup {
  key: string
  productName: string | null
  productBarcode: string | null
  orders: BatchQueryItem[]
}
interface CustomerGroup {
  customer: string
  products: ProductGroup[]
}

const grouped = computed<CustomerGroup[]>(() => {
  const wl = whitelistCustomers.value
  const wlSet = new Set(wl)
  const whitelistLoaded = wl.length > 0 || whitelistData.value !== undefined
  const map = new Map<string, Map<string, BatchQueryItem[]>>()
  const order: string[] = []

  for (const item of items.value) {
    if (whitelistLoaded && !wlSet.has(item.customer)) continue
    const cKey = item.customer
    if (!map.has(cKey)) {
      map.set(cKey, new Map())
      order.push(cKey)
    }
    const pMap = map.get(cKey)!
    const pKey = `${item.product_id}`
    if (!pMap.has(pKey)) {
      pMap.set(pKey, [])
    }
    pMap.get(pKey)!.push(item)
  }

  return order.map(c => ({
    customer: c,
    products: Array.from(map.get(c)!.entries()).map(([pKey, orders]) => ({
      key: pKey,
      productName: orders[0]!.product_name,
      productBarcode: orders[0]!.product_barcode,
      orders: orders.sort((a, b) => (a.order_date ?? '').localeCompare(b.order_date ?? '')),
    })),
  }))
})

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
    refetch()
  } catch {
    showToast('批次号更新失败', 'error')
  } finally {
    saving.value = false
  }
}

// ---- Complete batch ----
const showCompleteModal = ref(false)
const completingBatchNo = ref('')
const completing = ref(false)

/** 打开完成批次确认弹窗 */
function openCompleteConfirm(order: BatchQueryItem) {
  completingBatchNo.value = order.batch_no!
  showCompleteModal.value = true
}

/** 确认完成批次操作 */
async function confirmComplete() {
  completing.value = true
  try {
    await orderBatchApi.completeBatch({ batch_no: completingBatchNo.value })
    showToast('批次已完成', 'success')
    showCompleteModal.value = false
    refetch()
  } catch {
    showToast('批次完成操作失败', 'error')
  } finally {
    completing.value = false
  }
}
</script>

<style scoped>
/* ===== 容器 (Section 1) ===== */
.bt-container {
  padding: 0;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* ===== 卡片 (Section 3) ===== */
/* 卡片样式已迁移到全局 .page-card 系列（src/styles/app.css） */

/* ===== 卡片头部 (Section 4) ===== */
/* 卡片头部样式已迁移到全局 .page-card-header（src/styles/app.css） */
.page-card-header :deep(.ht-bar) {
  width: auto;
  margin: 0;
}

.bt-card-title-group {
  display: flex;
  align-items: center;
  gap: 10px;
}
.bt-card-title-group h3 {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  margin: 0;
}
.bt-card-title-group small {
  font-size: 12px;
  color: var(--color-text-secondary);
  margin: 0;
}

/* ===== 图标色块 (Section 8) ===== */
.bt-icon-box {
  width: 46px;
  height: 46px;
  border-radius: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 19px;
  flex-shrink: 0;
}
.bt-icon-blue {
  background: linear-gradient(135deg, var(--color-primary-100), var(--color-primary-200));
  color: var(--color-primary-600);
}

/* ===== 头部操作区 ===== */
.bt-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  order: 2;
}

.bt-header-search {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

/* ===== TAB 切换栏 (Section 23) ===== */
.bt-tab-group {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
}

.bt-tab-btn {
  padding: 8px 14px;
  border: none;
  border-radius: 9px;
  background: transparent;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: background 0.3s ease, color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
  font-family: inherit;
}
.bt-tab-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}
.bt-tab-btn--active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91, 141, 239, 0.2);
  transform: translateY(-1px);
}

/* ===== 卡片主体 (Section 3 overflow) ===== */
/* 卡片主体样式已迁移到全局 .page-card-main（src/styles/app.css） */

/* ===== 加载状态 (Section 18) ===== */
.bt-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 40px 20px;
}

/* ===== 空状态 (Section 18) ===== */
.bt-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 40px 20px;
  font-size: 14px;
  color: var(--color-text-muted);
}
.bt-empty i {
  font-size: 28px;
  opacity: 0.5;
}

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

/* ===== 批次号标签 ===== */
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

/* ===== 白名单设置按钮 ===== */
.bt-whitelist-btn {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 8px;
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  transition: background 0.2s ease, transform 0.2s ease;
}
.bt-whitelist-btn:hover {
  background: var(--color-primary-100);
  transform: translateY(-1px);
}

/* ===== 白名单弹窗 ===== */
.bt-whitelist-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.3);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.bt-whitelist-modal {
  background: white;
  border-radius: 16px;
  width: 360px;
  max-height: 480px;
  display: flex;
  flex-direction: column;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
}
.bt-whitelist-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  font-size: 15px;
  font-weight: 700;
  border-bottom: 1px solid var(--color-border-light);
}
.bt-whitelist-close {
  background: none;
  border: none;
  font-size: 20px;
  color: var(--color-text-muted);
  cursor: pointer;
  padding: 0 4px;
  line-height: 1;
}
.bt-whitelist-body {
  padding: 12px 20px;
  overflow-y: auto;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.bt-whitelist-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  font-size: 14px;
  color: var(--color-text);
  cursor: pointer;
}
.bt-whitelist-item input[type="checkbox"] {
  width: 16px;
  height: 16px;
  accent-color: var(--color-primary-500);
  cursor: pointer;
}
.bt-whitelist-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 20px;
  border-top: 1px solid var(--color-border-light);
}

/* ===== Fetching bar ===== */
.bt-fetching-bar {
  height: 2px;
  background: var(--color-primary-100);
  overflow: hidden;
  margin: 0 24px;
  border-radius: 1px;
}
.bt-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500);
  border-radius: 1px;
  animation: bt-progress-slide 1s ease-in-out infinite;
}
@keyframes bt-progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
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
  .page-card-header {
    padding: 12px 16px 8px;
  }
  .bt-filterbar {
    padding: 0 16px 12px;
  }
  .bt-groups {
    padding: 0 16px 12px;
  }
}
</style>
