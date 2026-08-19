<template>
  <div class="bo-inventory">
    <!-- 筛选区已迁移到 BeileOrderView 的 .page-card-header 右侧 -->

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
          <div class="bo-toolbar-right">
            <button v-if="canExport" type="button" class="bo-toolbar-btn bo-toolbar-btn--export" :disabled="exporting || displayOrders.length === 0" @click="handleExport">
              <FontAwesomeIcon icon="file-csv" aria-hidden="true" /> 导出
            </button>
            <button v-if="canPrint" type="button" class="bo-toolbar-btn bo-toolbar-btn--print" :disabled="selectedCount === 0" @click="handlePrint">
              <FontAwesomeIcon icon="print" aria-hidden="true" /> 打印
            </button>
          </div>
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
              :item-key="(i: BeileOrderRow) => i.id"
              class="bo-virtual-list"
            >
              <template #default="{ item }">
                <BeileOrderRow
                  :item="item"
                  :show-product-column="showProductColumn"
                  :confirm-status="confirmStatus"
                  :confirming-ids="confirmingIds"
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
 * 职责：以表格展示 factory=湖北 的订单，支持订单号/客户筛选与分页。
 * 数据获取复用 orderApi.beileList，锁定 factory=湖北。
 * 数据/确认逻辑下沉到 composables/useBeileOrders.ts，
 * 列表行拆分为 components/BeileOrderRow.vue，
 * 详情弹窗拆分为 components/BeileOrderDetailDialog.vue。
 */
import { ref, computed, watch, onUnmounted } from 'vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import UiCheckbox from '@/components/ui/UiCheckbox.vue'
import VirtualList from '@/components/ui/VirtualList.vue'
import BeileOrderRow from '@/views/beile-order/components/BeileOrderRow.vue'
import BeileOrderDetailDialog from '@/views/beile-order/components/BeileOrderDetailDialog.vue'
import { useBeileOrders } from '@/views/beile-order/composables/useBeileOrders'
import type { BeileOrderRow as BeileOrderRowType } from '@/views/beile-order/composables/useBeileOrders'
import { useAuthStore } from '@/stores/auth'
import { downloadXls } from '@/utils/xls'
import { printHtml } from '@/utils/print'
import { useExport } from '@/composables/useExport'
import { toast } from '@/composables/useToast'

// ==================== 列表：查询 + 筛选 + 分页 + 确认流程（useBeileOrders） ====================
const {
  PAGE_SIZE_OPTIONS,
  perPage,
  filters,
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
  unconfirmedCount,
  showProductColumn,
  displayOrders,
  highlightId,
  applyProductFilter,
  applyCustomerFilter,
  handleSearch,
  handleReset,
  goPage,
  setConfirmStatus,
  detailOpen,
  detailData,
  openDetail,
  confirmingIds,
  handleConfirm,
} = useBeileOrders()

/** 模板内 item-key 的行类型别名（保持泛型推断） */
type BeileOrderRow = BeileOrderRowType

// ==================== 导出 / 打印 ====================
const authStore = useAuthStore()
const { exporting, runExport } = useExport()

/** 权限：导出 / 打印（超级管理员自动放行） */
const canExport = computed(() => authStore.hasPermission('beile_order_export'))
const canPrint = computed(() => authStore.hasPermission('beile_order_print'))

/** 选中的订单 id 集合（批量打印用） */
const selectedIds = ref<Set<number>>(new Set())
const selectedCount = computed(() => selectedIds.value.size)

/** 当前展示列表是否有数据（导出按钮启用条件） */
const hasDisplayOrders = computed(() => displayOrders.value.length > 0)

/** 当前页是否全选（复选框 indeterminate 由 UiCheckbox 内部处理） */
const isAllSelected = computed(() =>
  displayOrders.value.length > 0 && displayOrders.value.every((o) => selectedIds.value.has(o.id)),
)

/** 切换单行选中 */
function toggleSelect(id: number) {
  const next = new Set(selectedIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selectedIds.value = next
}

/** 全选 / 取消全选当前页 */
function toggleSelectAll(checked: boolean) {
  const next = new Set(selectedIds.value)
  if (checked) {
    displayOrders.value.forEach((o) => next.add(o.id))
  } else {
    displayOrders.value.forEach((o) => next.delete(o.id))
  }
  selectedIds.value = next
}

/** 计算行总数量（多 SKU 汇总） */
function rowQuantity(item: BeileOrderRowType): number {
  const items = item.items || []
  if (items.length > 0) return items.reduce((sum, s) => sum + (s.quantity || 0), 0)
  return item.quantity || 0
}

/** 汇总表列头（含产品明细） */
const SUMMARY_HEADERS = [
  '订单类型', '下单时间', '客户名称', '工厂', '产品名称', '数量', '备注',
]

/** 汇总表各列宽度（px），用于导出 XLS 列宽分配 */
const SUMMARY_COL_WIDTHS = [90, 120, 130, 80, 220, 80, 180]

/** HTML 特殊字符转义 */
function escapeHtml(str: string): string {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

/**
 * 构建汇总表 tbody HTML。
 * 同一订单的订单类型/下单时间/客户名称/工厂列用 rowspan 合并单元格，
 * 产品名称/数量/备注每行独立输出。
 */
function buildSummaryTbody(items: BeileOrderRowType[]): string {
  let html = ''
  for (const item of items) {
    const type = item.record_type === 'stockin' ? '备货' : '订单'
    const factory = (item.factories || ['湖北']).join(', ')
    const orderCells = [type, item.order_date || '', item.customer || '', factory]
    const note = item.note || ''

    const skus = (item.items && item.items.length > 0)
      ? item.items
      : [{ product_name: item.product_name, quantity: item.quantity }]

    const rowspan = skus.length
    skus.forEach((sku, idx) => {
      const cells: string[] = []
      if (idx === 0) {
        for (const c of orderCells) {
          cells.push(`<td${rowspan > 1 ? ` rowspan="${rowspan}"` : ''}>${escapeHtml(c)}</td>`)
        }
      }
      cells.push(`<td>${escapeHtml(sku.product_name || '-')}</td>`)
      cells.push(`<td>${escapeHtml(String(sku.quantity || 0))}</td>`)
      cells.push(`<td>${idx === 0 ? escapeHtml(note) : ''}</td>`)
      html += `<tr>${cells.join('')}</tr>`
    })
  }
  return html
}

/** 导出当前页数据为 XLS */
function handleExport() {
  runExport(() => {
    const thead = `<tr>${SUMMARY_HEADERS.map((h, i) => `<th style="width:${SUMMARY_COL_WIDTHS[i]}px">${h}</th>`).join('')}</tr>`
    const tbody = buildSummaryTbody(displayOrders.value)
    const statusLabel = confirmStatus.value === 'unconfirmed' ? '未确认' : '已确认'
    const title = `湖北订单汇总（${statusLabel}）`
    const html = `<div style="text-align:center;margin-bottom:20px;"><h2>${title}</h2></div><table><thead>${thead}</thead><tbody>${tbody}</tbody></table>`
    const date = new Date().toISOString().slice(0, 10)
    downloadXls(html, `湖北订单_${statusLabel}_${date}.xls`)
  })
}

/** 批量打印选中订单汇总表 */
function handlePrint() {
  const targets = displayOrders.value.filter((o) => selectedIds.value.has(o.id))
  if (targets.length === 0) {
    toast.warning('请先勾选要打印的订单')
    return
  }
  const thead = `<tr>${SUMMARY_HEADERS.map((h) => `<th>${escapeHtml(h)}</th>`).join('')}</tr>`
  const tbody = buildSummaryTbody(targets)
  const printStyle = `
    body { font-family: SimSun, 宋体; padding: 20px; }
    table { width: 100%; border-collapse: collapse; }
    th, td { border: 1px solid #333; padding: 8px; font-size: 13px; text-align: center; }
    th { background: #e6e6e6; }
  `
  printHtml(`湖北订单汇总（${targets.length} 条）`, `<table><thead>${thead}</thead><tbody>${tbody}</tbody></table>`, printStyle)
  toast.success(`已发送 ${targets.length} 条订单至打印预览`)
}


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

// 翻页 / 筛选变化时清空选中并回到列表顶部（虚拟滚动不自动归位）
watch([page, appliedProduct, appliedCustomer, confirmStatus], () => {
  selectedIds.value = new Set()
  virtualListRef.value?.scrollToTop()
})

/**
 * 暴露给父组件（HubeiView）使用。
 * 筛选 UI 已迁移到 header 右侧，但状态与方法仍在 Tab 内统一管控。
 * 导出/打印按钮也迁移到 header 搜索框右侧，相关状态与方法经 ref 暴露。
 * 注意：必须同时传入实际 ref 值（仅写类型标注不会暴露任何东西）。
 */
defineExpose({
  filters,
  handleSearch,
  handleReset,
  applyProductFilter,
  applyCustomerFilter,
  confirmStatus,
  setConfirmStatus,
  unconfirmedCount,
  // 导出 / 打印（头部按钮使用）
  canExport,
  canPrint,
  exporting,
  selectedCount,
  hasDisplayOrders,
  handleExport,
  handlePrint,
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
