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
            <div class="bo-table-inner" :style="{ minWidth: tableMinWidth() + 'px' }">
              <!-- 表头（独立于虚拟滚动，粘在顶部）；右内边距 = 纵向滚动条宽度，保证与行左对齐 -->
              <div class="bo-grid bo-grid-header" :style="{ paddingRight: scrollbarWidth + 'px' }">
                <div v-if="canPrint" class="bo-th bo-th-center bo-th-select" style="width: 40px;">
                  <UiCheckbox :checked="isAllSelected" @update:checked="toggleSelectAll" />
                </div>
                <div class="bo-th bo-th-center" style="width: 90px;">订单类型</div>
                <div class="bo-th bo-th-center" style="width: 150px;">下单时间</div>
                <div class="bo-th bo-th-center" style="width: 170px;">客户名称</div>
                <div class="bo-th bo-th-center" style="width: 100px;">工厂</div>
                <!-- 产品名称：搜索态专属列（后端按 product 参数收窄 items 到命中 SKU） -->
                <div v-if="appliedProduct" class="bo-th bo-th-center" style="width: 180px;">产品名称</div>
                <div class="bo-th bo-th-center" style="width: 90px;">SKU</div>
                <div class="bo-th bo-th-center" style="width: 110px;">订单数量</div>
                <div class="bo-th bo-th-center" style="width: 110px;" title="生产数量 = 订单数量 + 备品数量">生产数量</div>
                <div class="bo-th bo-th-center" style="width: 110px;">小义开单</div>
                <div v-if="confirmStatus !== 'unconfirmed'" class="bo-th bo-th-center" style="width: 110px;">确认状态</div>
                <div v-if="confirmStatus !== 'confirmed'" class="bo-th bo-th-center" style="width: 130px;">确认操作</div>
                <div class="bo-th bo-th-left" style="width: 160px;">备注</div>
              </div>

              <!-- 虚拟滚动主体：固定行高（汇总单行，无展开） -->
              <div ref="listAreaRef" class="bo-list-area">
                <VirtualList
                  v-if="listAreaHeight > 0"
                  ref="virtualListRef"
                  :items="displayOrders"
                  :item-height="56"
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
                      :has-keyword="!!appliedProduct"
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

// ==================== 虚拟滚动容器高度测量 ====================
const listAreaRef = ref<HTMLElement | null>(null)
const listAreaHeight = ref(0)
const virtualListRef = ref<{
  scrollToTop: () => void
} | null>(null)

function measureListArea() {
  if (listAreaRef.value) {
    listAreaHeight.value = listAreaRef.value.clientHeight
  }
}

// 水平滚动所需的最小宽度 = 各列最小宽之和（与表头 / 行内联列宽一致）
function tableMinWidth() {
  let w = 90 + 150 + 170 + 100 + 90 + 110 + 110 + 110 + 160
  if (canPrint.value) w += 40
  if (appliedProduct.value) w += 180
  if (confirmStatus.value !== 'unconfirmed') w += 110
  if (confirmStatus.value !== 'confirmed') w += 130
  return w
}

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
.bo-grid {
  display: flex;
  width: 100%;
  font-size: 13px;
}
.bo-grid-header {
  flex-shrink: 0;
  box-sizing: border-box;
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
  letter-spacing: 0.02em;
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
