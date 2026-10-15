<template>
  <div class="bo-inventory">
    <!-- 筛选区在 HubeiView 的 .page-card-header 右侧 -->

    <!-- 表格区 -->
    <div class="bo-card-main">
      <div v-if="isLoading && orders.length === 0" class="bo-empty">
        <UiSpinner />
      </div>
      <div v-else-if="orders.length === 0" class="bo-empty">
        <FontAwesomeIcon icon="clipboard-list" aria-hidden="true" />
        <span>暂无订单</span>
      </div>
      <template v-else>
        <div v-if="isFetching" class="bo-fetching-bar"><div class="bo-fetching-progress" /></div>
        <!-- 导出 / 打印已上移至页头右上角（HubeiView .hu-header-actions） -->
        <div class="bo-table-wrap">
          <!-- 水平滚动容器：表头与虚拟列表主体同处其中 → 横向滚动天然同步 -->
          <div class="bo-table-scroll">
            <div class="bo-table-inner" :style="{ minWidth: tableMinWidth + 'px' }">
              <!-- 表头（独立于虚拟滚动，粘在顶部）；与行块同用 beileGridTemplate 列模板，逐列对齐 -->
              <div
                class="bo-grid bo-grid-header"
                :style="{ paddingRight: scrollbarWidth + 'px', gridTemplateColumns: gridTemplate }"
              >
                <div
                  v-for="col in cols"
                  :key="col.key"
                  class="bo-th"
                  :class="[`bo-th-${col.align}`, { 'bo-th-select': col.key === 'select' }]"
                >
                  <UiCheckbox
                    v-if="col.key === 'select'"
                    :checked="isAllSelected"
                    @update:checked="toggleSelectAll"
                  />
                  <template v-else-if="col.key === 'prodQty'">
                    <span title="生产数量 = 订单数量 + 备品数量">生产数量</span>
                  </template>
                  <template v-else>{{ col.label }}</template>
                </div>
              </div>

              <!-- 虚拟滚动主体：订单块变高（行块高度 = SKU 行数 × 56px），dynamicHeight 自适应 -->
              <div ref="listAreaRef" class="bo-list-area">
                <VirtualList
                  v-if="listAreaHeight > 0"
                  ref="virtualListRef"
                  :items="displayOrders"
                  :dynamic-height="true"
                  :estimated-height="estimatedBlockHeight"
                  :item-height="BEILE_ROW_HEIGHT"
                  :container-height="listAreaHeight"
                  :item-key="(i: BeileOrderRowType) => i.id"
                  class="bo-virtual-list"
                >
                  <template #default="{ item }">
                    <BeileOrderRow
                      :item="item"
                      :confirm-status="confirmStatus"
                      :is-confirming="confirmingIds.has(item.id)"
                      :highlight-id="highlightId"
                      :confirmable="canConfirm"
                      :selectable="canPrint"
                      :selected="selectedIds.has(rowKey(item))"
                      :keyword="appliedProduct"
                      @open="openDetail"
                      @confirm="handleConfirm"
                      @toggle-select="toggleSelect"
                    />
                  </template>
                </VirtualList>
              </div>
            </div>
          </div>

          <div v-if="displayOrders.length === 0" class="bo-empty bo-empty-inline">
            <FontAwesomeIcon icon="search-minus" aria-hidden="true" />
            <span>未找到包含该关键字的订单</span>
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

    <!-- 订单详情弹窗（两级结构之二：SKU 明细） -->
    <BeileOrderDetailDialog v-model:open="detailOpen" :detail-data="detailData" />
  </div>
</template>

<script setup lang="ts">
/**
 * BeileOrderTab.vue — 湖北订单汇总列表子组件（两级结构之一级）
 *
 * 职责：以虚拟滚动表格展示 factory=湖北 的订单，一行一单（订单级汇总）。
 * 逐 SKU 明细下沉到详情弹窗（BeileOrderDetailDialog），列表不再承载 SKU 行，
 * 消除多 SKU 订单在单行中的信息拥挤。
 * 数据/筛选/分页/确认/选中/导出/打印逻辑下沉到
 * composables/useBeileOrders.ts，由父组件 HubeiView 通过
 * provide/inject 共享同一状态实例，本组件仅注入并负责
 * 虚拟滚动容器高度测量与滚动归位。
 */
import { ref, computed, watch, onUnmounted, nextTick } from 'vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import UiCheckbox from '@/components/ui/UiCheckbox.vue'
import VirtualList from '@/components/ui/VirtualList.vue'
import BeileOrderRow from '@/views/beile-order/components/BeileOrderRow.vue'
import BeileOrderDetailDialog from '@/views/beile-order/components/BeileOrderDetailDialog.vue'
import {
  injectBeileOrders,
  BEILE_ROW_HEIGHT,
  beileColumns,
  beileGridTemplate,
  beileMinWidth,
  beileBlockView,
} from '@/views/beile-order/composables/useBeileOrders'
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
  displayOrders,
  highlightId,
  goPage,
  detailOpen,
  detailData,
  openDetail,
  confirmingIds,
  handleConfirm,
  rowKey,
  selectedIds,
  isAllSelected,
  toggleSelect,
  toggleSelectAll,
  canConfirm,
  canPrint,
} = injectBeileOrders()

// ==================== 列布局（与行块共用 beileColumns 单一真源） ====================
const cols = computed(() => beileColumns({ canPrint: canPrint.value, confirmStatus: confirmStatus.value }))
const gridTemplate = computed(() => beileGridTemplate(cols.value))
const tableMinWidth = computed(() => beileMinWidth(cols.value))

/**
 * 变高虚拟滚动的「预估块高」：订单块高度 = (SKU 行数 + 多 SKU 合计行) × 56px。
 * 块行数由 beileBlockView 单一真源派生（与页面行块、导出同源，杜绝布局分叉）。
 * 用当前页平均块高作预估值，首屏占位更贴近真实；实际高度由 VirtualList 的
 * ResizeObserver 测量后逐块校正（min-height 占位 + measureItems）。
 */
const estimatedBlockHeight = computed(() => {
  const list = displayOrders.value
  if (list.length === 0) return BEILE_ROW_HEIGHT
  let total = 0
  for (const o of list) total += beileBlockView(o, appliedProduct.value).span * BEILE_ROW_HEIGHT
  return Math.max(BEILE_ROW_HEIGHT, Math.round(total / list.length))
})

// ==================== 虚拟滚动容器高度测量 ====================
const listAreaRef = ref<HTMLElement | null>(null)
const listAreaHeight = ref(0)
const virtualListRef = ref<{
  scrollToTop: () => void
  measureItems?: () => void
  remeasureItem?: (index: number) => void
} | null>(null)

function measureListArea() {
  if (listAreaRef.value) {
    listAreaHeight.value = listAreaRef.value.clientHeight
  }
}

// 展示列表变化（翻页/筛选/确认乐观移除）后作废全部块高缓存并重测：
// dynamicHeight 的 min-height 占位会顶住旧高度，不作废则新页块高错乱。
watch(displayOrders, () => {
  nextTick(() => virtualListRef.value?.measureItems?.())
})

/** 纵向滚动条宽度：表头需预留等宽右内边距，使末列与行左对齐 */
const scrollbarWidth = ref(0)
function measureScrollbarWidth() {
  const scroller = listAreaRef.value?.querySelector<HTMLElement>('.virtual-list-container')
  scrollbarWidth.value = scroller ? Math.max(0, scroller.offsetWidth - scroller.clientWidth) : 0
}

// bo-list-area 在 v-else 分支内，首次加载（isLoading）时该 DOM 不存在，
// onMounted 无法测量其高度（listAreaHeight 恒为 0 → VirtualList 不渲染）。
let areaResizeObserver: ResizeObserver | null = null
watch(listAreaRef, (el) => {
  areaResizeObserver?.disconnect()
  areaResizeObserver = null
  if (!el) return
  measureListArea()
  measureScrollbarWidth()
  if (typeof ResizeObserver !== 'undefined') {
    areaResizeObserver = new ResizeObserver(() => {
      measureListArea()
      measureScrollbarWidth()
    })
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
/* 导出 / 打印按钮样式已随按钮迁至 HubeiView（.hu-header-actions） */

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
.bo-table-wrap {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.bo-table-scroll {
  flex: 1;
  min-height: 0;
  overflow-x: auto;
  overflow-y: hidden;
}
.bo-table-inner {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
/* 表头：CSS Grid，列模板由 beileGridTemplate 与行块同源（逐列对齐） */
.bo-grid {
  display: grid;
  width: 100%;
  font-size: 13px;
}
.bo-grid-header {
  flex-shrink: 0;
  box-sizing: border-box;
}
.bo-th {
  box-sizing: border-box;
  padding: 10px 14px;
  border-right: 1px solid #d8dce2;
  overflow: hidden;
  display: flex;
  align-items: center;
  background: var(--color-surface, #f8fafc);
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.02em;
  border-bottom: 2px solid #b8bec6;
  color: var(--color-text-secondary);
  white-space: nowrap;
}
.bo-th:last-child {
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
.bo-th-select {
  padding: 10px 8px;
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
