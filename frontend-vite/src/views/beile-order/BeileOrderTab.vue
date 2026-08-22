<template>
  <div class="bo-inventory">
    <!-- 筛选区在 HubeiView 的 .page-card-header 右侧 -->

    <!-- 表格区 -->
    <div class="bo-card-main">
      <!-- 确认状态筛选（未确认/已确认 TAB）已合并到 HubeiView 头部搜索栏位置 -->
      <!-- 未确认提醒横幅已迁移至 HubeiView 头部「已确认」TAB 右侧 -->
      <div v-if="isLoading && orders.length === 0" class="bo-empty">
        <UiSpinner />
      </div>
      <div v-else-if="orders.length === 0" class="bo-empty">
        <FontAwesomeIcon icon="clipboard-list" aria-hidden="true" />
        <span>暂无外发工序</span>
      </div>
      <template v-else>
        <div v-if="isFetching" class="bo-fetching-bar"><div class="bo-fetching-progress" /></div>
        <!-- 工具栏：导出 / 打印 -->
        <div class="bo-toolbar">
          <div class="bo-toolbar-left">
            <span v-if="canPrint && selectedCount > 0" class="bo-selected-count">已选 {{ selectedCount }} 条</span>
          </div>
          <div class="bo-toolbar-right" />
        </div>
        <div class="bo-table-wrap">
          <!-- 表头（独立于虚拟滚动，粘在顶部） -->
          <div class="bo-grid bo-grid-header">
            <div v-if="canPrint" class="bo-th bo-th-center bo-th-select" style="width: 40px;">
              <UiCheckbox :checked="isAllSelected" @update:checked="toggleSelectAll" />
            </div>
            <div class="bo-th bo-th-center" style="width: 90px;">订单类型</div>
            <div class="bo-th bo-th-center" style="width: 170px;">下单时间</div>
            <div class="bo-th bo-th-center" style="width: 170px;">客户名称</div>
            <div v-if="showProductColumn" class="bo-th bo-th-center" style="width: 180px;">产品名称</div>
            <div class="bo-th bo-th-center" style="width: 100px;">工厂</div>
            <div class="bo-th bo-th-center" style="width: 130px;">数量</div>
            <div v-if="confirmStatus !== 'unconfirmed'" class="bo-th bo-th-center" style="width: 110px;">确认状态</div>
            <div v-if="confirmStatus !== 'confirmed'" class="bo-th bo-th-center" style="width: 130px;">确认操作</div>
            <div class="bo-th bo-th-left" style="width: 160px;">备注</div>
          </div>

          <!-- 虚拟滚动主体：只渲染视口附近的订单行（多 SKU 变高行自动测量） -->
          <div ref="listAreaRef" class="bo-list-area">
            <VirtualList
              v-if="listAreaHeight > 0"
              ref="virtualListRef"
              :items="displayOrders"
              :item-height="54"
              :estimated-height="54"
              dynamic-height
              :container-height="listAreaHeight"
              :item-key="(i: BeileOrderRowType) => i.id"
              class="bo-virtual-list"
            >
              <template #default="{ item }">
                <BeileOrderRow
                  :item="item"
                  :show-product-column="showProductColumn"
                  :confirm-status="confirmStatus"
                  :is-confirming="confirmingIds.has(item.id)"
                  :highlight-id="highlightId"
                  :keyword="appliedProduct"
                  :selectable="canPrint"
                  :selected="selectedIds.has(item.id)"
                  @open="openDetail"
                  @confirm="handleConfirm"
                  @toggle-select="toggleSelect"
                />
              </template>
            </VirtualList>
          </div>

          <div v-if="displayOrders.length === 0" class="bo-empty bo-empty-inline">
            <FontAwesomeIcon icon="search-minus" aria-hidden="true" />
            <span>当前页未匹配到该订单号</span>
          </div>
        </div>

        <UiPagination
          v-if="totalPages > 1"
          :current-page="currentPage"
          :total-pages="totalPages"
          :total-items="totalItems"
          :page-size="perPage"
          :page-size-options="PAGE_SIZE_OPTIONS"
          @update:current-page="goPage"
          @update:page-size="perPage = $event"
        />
      </template>
    </div>

    <!-- 订单详情弹窗（拆分为子组件） -->
    <BeileOrderDetailDialog v-model:open="detailOpen" :detail-data="detailData" />
  </div>
</template>

<script setup lang="ts">
/**
 * BeileOrderTab.vue — 湖北订单列表子组件
 *
 * 职责：以虚拟滚动表格展示 factory=湖北 的订单。
 * 数据/筛选/分页/确认/选中/导出/打印逻辑全部下沉到
 * composables/useBeileOrders.ts，由父组件 HubeiView 通过
 * provide/inject 共享同一状态实例，本组件仅注入并负责
 * 虚拟滚动容器高度测量与滚动归位。
 */
import { ref, watch, onUnmounted } from 'vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import UiCheckbox from '@/components/ui/UiCheckbox.vue'
import VirtualList from '@/components/ui/VirtualList.vue'
import BeileOrderRow from '@/views/beile-order/components/BeileOrderRow.vue'
import BeileOrderDetailDialog from '@/views/beile-order/components/BeileOrderDetailDialog.vue'
import { injectBeileOrders } from '@/views/beile-order/composables/useBeileOrders'
import type { BeileOrderRow as BeileOrderRowType } from '@/views/beile-order/composables/useBeileOrders'

const {
  PAGE_SIZE_OPTIONS,
  perPage,
  appliedProduct,
  appliedCustomer,
  confirmStatus,
  page,
  currentPage,
  totalItems,
  totalPages,
  isLoading,
  isFetching,
  orders,
  showProductColumn,
  displayOrders,
  highlightId,
  goPage,
  detailOpen,
  detailData,
  openDetail,
  confirmingIds,
  handleConfirm,
  selectedIds,
  selectedCount,
  isAllSelected,
  toggleSelect,
  toggleSelectAll,
  canPrint,
} = injectBeileOrders()


// ==================== 虚拟滚动容器高度测量 ====================
const listAreaRef = ref<HTMLElement | null>(null)
const listAreaHeight = ref(0)
// VirtualList 为泛型组件，InstanceType 无法推导，用结构化类型描述所需句柄
const virtualListRef = ref<{ scrollToTop: () => void } | null>(null)

let areaResizeObserver: ResizeObserver | null = null

function measureListArea() {
  if (listAreaRef.value) {
    listAreaHeight.value = listAreaRef.value.clientHeight
  }
}

// bo-list-area 在 v-else 分支内，首次加载（isLoading）时该 DOM 不存在，
// onMounted 无法测量其高度（listAreaHeight 恒为 0 → VirtualList 不渲染）。
// 改为 watch template ref：元素出现后测量高度并挂载 ResizeObserver。
watch(listAreaRef, (el) => {
  areaResizeObserver?.disconnect()
  areaResizeObserver = null
  if (!el) return
  measureListArea()
  if (typeof ResizeObserver !== 'undefined') {
    areaResizeObserver = new ResizeObserver(measureListArea)
    areaResizeObserver.observe(el)
  }
}, { flush: 'post' })

onUnmounted(() => {
  areaResizeObserver?.disconnect()
})

// 翻页 / 筛选变化时回到列表顶部（选中清空已在 composable 处理）
watch([page, appliedProduct, appliedCustomer, confirmStatus], () => {
  virtualListRef.value?.scrollToTop()
})
</script>

<style scoped>
/* ===== 工具栏：导出 / 打印 ===== */
.bo-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 4px;
  flex-shrink: 0;
}
.bo-toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.bo-toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.bo-selected-count {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-primary-600, #2563eb);
}
.bo-toolbar-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  font-size: 13px;
  font-weight: 600;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 8px;
  background: #fff;
  color: var(--color-text-secondary, #475569);
  cursor: pointer;
  font-family: inherit;
  transition: all 0.15s ease;
  white-space: nowrap;
}
.bo-toolbar-btn:hover:not(:disabled) {
  border-color: var(--color-primary-300, #93c5fd);
  color: var(--color-primary-600, #2563eb);
  background: var(--color-primary-50, #eff6ff);
}
.bo-toolbar-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.bo-toolbar-btn--export:hover:not(:disabled) {
  border-color: var(--color-success-400, #4ade80);
  color: var(--color-success-600, #16a34a);
  background: var(--color-success-50, #f0fdf4);
}
.bo-toolbar-btn--print:hover:not(:disabled) {
  border-color: var(--color-warning-400, #fbbf24);
  color: var(--color-warning-600, #d97706);
  background: var(--color-warning-50, #fffbeb);
}
.bo-th-select {
  padding: 10px 8px;
}

.bo-inventory {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

/* ===== 表格区 ===== */
.bo-card-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
/* 表格区自身滚动：让分页按钮固定贴在卡片底部，
   避免行数/多 SKU 高度变化时翻页按钮上下跳动 */
/* 表格不设边框：卡片自身已有边框，订单列左侧不再出现重复线条
   （对齐客户/库存页的裸表格风格）；分页栏自带顶边作分隔线 */
.bo-table-wrap {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
/* 虚拟滚动表格：flex 网格布局，列宽与表头/行一致 */
.bo-grid {
  display: flex;
  width: 100%;
  font-size: 13px;
}
.bo-grid-header {
  flex-shrink: 0;
}
.bo-th {
  box-sizing: border-box;
  flex: 0 0 auto;
  padding: 10px 14px;
  border-right: 1px solid #d8dce2;
  overflow: hidden;
  display: flex;
  align-items: center;
  background: var(--color-surface, #f8fafc);
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 2px solid #b8bec6;
  color: var(--color-text-secondary);
  white-space: nowrap;
}
.bo-th:last-child {
  flex: 1 1 auto;
  min-width: 160px;
  border-right: none;
}
.bo-th-left {
  text-align: left !important;
  justify-content: flex-start;
}
.bo-th-center {
  text-align: center !important;
  justify-content: center;
}

/* ===== 虚拟滚动列表区 ===== */
.bo-list-area {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  position: relative;
}
.bo-virtual-list {
  height: 100%;
}

/* ===== 未确认订单提醒横幅（湖北订单确认流程） ===== */
.bo-unconfirmed-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  padding: 10px 16px;
  background: var(--color-warning-50);
  border: 1px solid var(--color-warning-200);
  border-radius: 10px;
  color: var(--color-warning-700);
  font-size: 13px;
  font-weight: 600;
  flex-shrink: 0;
}
.bo-unconfirmed-banner svg {
  flex-shrink: 0;
}
.bo-unconfirmed-banner strong {
  color: var(--color-warning-800);
  font-size: 15px;
}

/* ===== 空/加载态 ===== */
.bo-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-text-muted);
}
.bo-empty i {
  font-size: 28px;
  opacity: 0.5;
}
.bo-empty span {
  font-size: 14px;
}
.bo-empty-inline {
  padding: 24px 20px;
}

/* Fetching progress bar */
.bo-fetching-bar {
  height: 2px;
  background: var(--color-primary-100, #e0f2fe);
  overflow: hidden;
  border-radius: 1px;
}
.bo-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500, #3b82f6);
  border-radius: 1px;
  animation: bo-progress-slide 1s ease-in-out infinite;
}
@keyframes bo-progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}
</style>
