<template>
  <div class="bo-inventory">
    <!-- 筛选区已迁移到 BeileOrderView 的 .page-card-header 右侧 -->

    <!-- 表格区 -->
    <div class="bo-card-main">
      <!-- 确认状态筛选（未确认/已确认 TAB）已合并到 HubeiView 头部搜索栏位置 -->
      <!-- 湖北新订单未确认提醒横幅（全局未确认订单数，不受分页/筛选影响） -->
      <div v-if="unconfirmedCount > 0" class="bo-unconfirmed-banner">
        <FontAwesomeIcon icon="exclamation-triangle" aria-hidden="true" />
        <span>湖北新订单提醒：共有 <strong>{{ unconfirmedCount }}</strong> 个订单待确认，请及时确认</span>
      </div>
      <div v-if="isLoading && orders.length === 0" class="bo-empty">
        <UiSpinner />
      </div>
      <div v-else-if="orders.length === 0" class="bo-empty">
        <FontAwesomeIcon icon="clipboard-list" aria-hidden="true" />
        <span>暂无外发工序</span>
      </div>
      <template v-else>
        <div v-if="isFetching" class="bo-fetching-bar"><div class="bo-fetching-progress" /></div>
        <div class="bo-table-wrap">
          <!-- 表头（独立于虚拟滚动，粘在顶部） -->
          <div class="bo-grid bo-grid-header">
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
                <div
                  :class="['bo-grid bo-grid-row bo-row-clickable', { 'bo-row-highlight': highlightId !== null && String(item.id) === highlightId, 'bo-row-multi-sku': (item.items?.length || 1) > 1 }]"
                  @click="openDetail(item)"
                >
                  <div class="bo-td bo-td-center bo-td-middle bo-td-nowrap" style="width: 170px;">
                    <div class="bo-order-meta-cell">
                      <span v-if="item.record_type === 'stockin'" class="bo-type-badge bo-type-badge--stockin">备货</span>
                      <span v-else class="bo-type-badge bo-type-badge--order">订单</span>
                      <span class="bo-order-date" :title="item.order_date || ''">{{ item.order_date || '-' }}</span>
                    </div>
                  </div>
                  <div class="bo-td bo-td-center bo-td-middle bo-customer-cell" style="width:170px">{{ item.customer || '-' }}</div>
                  <div v-if="showProductColumn" class="bo-td bo-td-center bo-product-cell" style="width: 180px;">
                    <template v-if="visibleSkus(item).length > 0">
                      <div v-for="sku in visibleSkus(item)" :key="sku.id" class="bo-sku-line">
                        <span class="bo-sku-name" :title="sku.product_name || ''">{{ sku.product_name || '-' }}</span>
                      </div>
                    </template>
                    <span v-else class="bo-sku-name">{{ item.product_name || '-' }}</span>
                  </div>
                  <div class="bo-td bo-td-center bo-td-middle" style="width: 100px;"><span class="bo-cell-main">{{ item.factories?.join(', ') || '湖北' }}</span></div>
                  <div class="bo-td bo-td-center bo-td-middle" style="width: 130px;">
                    <template v-if="showProductColumn && visibleSkus(item).length > 0">
                      <strong>{{ visibleSkus(item).reduce((sum, s) => sum + (s.quantity || 0), 0) }}</strong>
                    </template>
                    <template v-else-if="item.items && item.items.length > 0">
                      <strong>{{ item.items.reduce((sum, s) => sum + (s.quantity || 0), 0) }}</strong>
                    </template>
                    <template v-else><strong>{{ item.quantity }}</strong></template>
                  </div>
                  <!-- 确认状态列：仅湖北订单参与确认流程，备货记录不适用；未确认 TAB 下整列隐藏（冗余） -->
                  <div v-if="confirmStatus !== 'unconfirmed'" class="bo-td bo-td-center bo-td-middle" style="width: 110px;">
                    <template v-if="item.record_type === 'order'">
                      <span v-if="item.confirmed" class="bo-confirm-badge bo-confirm-badge--done">已确认</span>
                      <span v-else class="bo-confirm-badge bo-confirm-badge--pending">未确认</span>
                    </template>
                    <span v-else class="bo-cell-muted">-</span>
                  </div>
                  <!-- 确认操作列：未确认订单显示确认按钮，已确认订单显示已确认徽章（已确认 TAB 隐藏整列） -->
                  <div v-if="confirmStatus !== 'confirmed'" class="bo-td bo-td-center bo-td-middle" style="width: 130px;">
                    <template v-if="item.record_type === 'order'">
                      <button
                        v-if="!item.confirmed"
                        class="bo-confirm-btn"
                        :disabled="confirmingIds.has(item.id)"
                        @click.stop="handleConfirm(item)"
                      >
                        {{ confirmingIds.has(item.id) ? '确认中…' : '确认订单' }}
                      </button>
                      <span v-else class="bo-confirm-badge bo-confirm-badge--done">已确认</span>
                    </template>
                    <span v-else class="bo-cell-muted">-</span>
                  </div>
                  <div class="bo-td bo-td-left bo-td-middle" style="width: 160px;">
                    <template v-if="visibleSkus(item).length > 0">
                      <div v-for="sku in visibleSkus(item)" :key="sku.id" class="bo-sku-line">
                        <span v-if="sku.note" class="bo-sku-note" :title="sku.note">{{ sku.note }}</span>
                      </div>
                    </template>
                    <span v-if="item.note" class="bo-sku-note">{{ item.note }}</span>
                  </div>
                </div>
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

    <!-- 订单详情弹窗 -->
    <UiDialog v-model:open="detailOpen" title="订单详情" max-width-class="max-w-[900px]">
      <div v-if="detailData" class="bo-detail-body">
        <!-- 基础信息行：一行展示 -->
        <div class="bo-detail-meta-row">
          <span class="bo-detail-meta-item"><span class="bo-detail-meta-label">下单时间</span> {{ detailData.order_date || '-' }}</span>
          <span class="bo-detail-meta-sep">|</span>
          <span class="bo-detail-meta-item"><span class="bo-detail-meta-label">客户</span> {{ detailData.customer || '-' }}</span>
          <span class="bo-detail-meta-sep">|</span>
          <span class="bo-detail-meta-item"><span class="bo-detail-meta-label">工厂</span> {{ detailData.factories?.join(', ') || '湖北' }}</span>
          <span class="bo-detail-meta-sep">|</span>
          <span class="bo-detail-meta-item"><span class="bo-detail-meta-label">总数量</span> <strong class="bo-detail-meta-num">{{ detailTotalQuantity }}</strong></span>
        </div>

        <!-- 确认信息：仅湖北订单参与确认流程，备货记录不展示 -->
        <div v-if="detailData.record_type === 'order'" class="bo-detail-meta-row">
          <span class="bo-detail-meta-item">
            <span class="bo-detail-meta-label">确认状态</span>
            <span v-if="detailData.confirmed" class="bo-confirm-badge bo-confirm-badge--done">已确认</span>
            <span v-else class="bo-confirm-badge bo-confirm-badge--pending">未确认</span>
          </span>
          <span class="bo-detail-meta-sep">|</span>
          <span class="bo-detail-meta-item"><span class="bo-detail-meta-label">确认时间</span> {{ detailData.confirmed_at || '-' }}</span>
          <span class="bo-detail-meta-sep">|</span>
          <span class="bo-detail-meta-item"><span class="bo-detail-meta-label">确认人</span> {{ detailData.confirmed_by || '-' }}</span>
        </div>

        <!-- SKU 明细表格 -->
        <div class="bo-detail-table-wrap">
          <table class="bo-detail-table">
            <thead>
              <tr>
                <th style="width:38%">产品名称</th>
                <th style="width:18%">产品条码</th>
                <th style="width:10%;text-align:right">数量</th>
                <th style="width:34%">备注</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(sku, idx) in (detailData.items || []).length > 0 ? detailData.items! : ([{}] as OrderSKU[])" :key="sku.id ?? idx">
                <td class="bo-detail-td-name">{{ sku.product_name || detailData.product_name || '-' }}</td>
                <td class="bo-detail-td-barcode">{{ sku.product_barcode || detailData.barcode || '-' }}</td>
                <td class="bo-detail-td-qty"><strong>{{ sku.quantity ?? detailData.quantity }}</strong></td>
                <td class="bo-detail-td-note" :title="(sku.note || detailData.note || '')">{{ sku.note || detailData.note || '-' }}</td>
              </tr>
              <tr v-if="(detailData.items || []).length === 0 && !detailData.product_name">
                <td colspan="4" class="bo-detail-td-empty">暂无 SKU 明细</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <template #footer>
        <UiButton variant="outline" @click="detailOpen = false">关闭</UiButton>
      </template>
    </UiDialog>
  </div>
</template>

<script setup lang="ts">
/**
 * BeileOrderTab.vue — 湖北订单列表子组件
 *
 * 职责：以表格展示 factory=湖北 的订单，支持订单号/客户筛选与分页。
 * 数据获取复用 orderApi.beileList，锁定 factory=湖北。
 */
import { reactive, computed, ref, watch, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { useQuery, useQueryClient, keepPreviousData } from '@tanstack/vue-query'
import { orderApi } from '@/api'
import type { OrderItem, OrderSKU } from '@/types'
import type { OrderListApiResponse } from '@/api/order'
import UiPagination from '@/components/ui/UiPagination.vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiButton from '@/components/ui/UiButton.vue'
import VirtualList from '@/components/ui/VirtualList.vue'
import { toast } from '@/composables/useToast'

/** 每页条数选项（分页组件下拉可选） */
const PAGE_SIZE_OPTIONS = [18, 30, 50, 100]

/** 当前每页条数，可由分页组件修改 */
const perPage = ref(18)

/** 湖北订单行：OrderItem 在后端实际响应中还包含 order_no / customer / product（未在 OrderItem 类型中声明） */
type BeileOrderRow = OrderItem & {
  order_no?: string
  customer?: string
  record_type?: 'order' | 'stockin'
  factories?: string[]
  /** 后端 beile-list 返回的首个 SKU 产品图路径 */
  product_image?: string | null
  /** 湖北订单确认状态：confirmed=false 即「未确认订单」 */
  confirmed?: boolean
  confirmed_at?: string
  confirmed_by?: string
  product?: { id: number; name: string; barcode: string; image: string }
}

/**
 * 输入文本与已应用筛选分离：
 * - filters.orderNo / filters.customer = 输入框显示文本（用户自由键入，不触发筛选）
 * - appliedProduct / appliedCustomer = 已确认的筛选值（选择建议 / 点击查询后生效）
 */
const filters = reactive({ orderNo: '', customer: '' })
const appliedProduct = ref('')
const appliedCustomer = ref('')

/** 确认状态筛选：unconfirmed=未确认 / confirmed=已确认（默认未确认，湖北订单确认流程） */
const confirmStatus = ref('unconfirmed')

const page = ref(1)

const currentPage = computed(() => page.value)
const totalItems = computed(() => ordersData.value?.total ?? 0)
const totalPages = computed(() => Math.max(1, Math.ceil(totalItems.value / perPage.value)))

/** 湖北订单列表查询 key：随筛选/分页变化（乐观更新时复用同一 key） */
const queryKey = computed(() =>
  ['beile-orders', appliedCustomer.value, confirmStatus.value, page.value, perPage.value] as const,
)

const {
  data: ordersData,
  isLoading,
  isFetching,
  refetch,
} = useQuery({
  queryKey,
  queryFn: () =>
    orderApi.beileList({
      customer: appliedCustomer.value || undefined,
      confirm_status: confirmStatus.value || undefined,
      page: page.value,
      per_page: perPage.value,
    }),
  staleTime: 30_000,
  gcTime: 60_000,
  // 定时刷新：新到湖北订单（未确认提醒横幅）无需手动刷新即可出现
  refetchInterval: 30_000,
  placeholderData: keepPreviousData,
})

/** 服务端返回的订单列表（已应用 customer 筛选与分页） */
const orders = computed<BeileOrderRow[]>(() => (ordersData.value?.data ?? []) as BeileOrderRow[])

/** 湖北订单确认流程：未确认订单总数（全局，列表顶部横幅用） */
const unconfirmedCount = computed(() => ordersData.value?.unconfirmed_count ?? 0)

/** 搜索产品时是否显示产品名称列：仅当已应用产品关键字筛选时显示 */
const showProductColumn = computed(() => appliedProduct.value.trim() !== '')

/** SKU 是否匹配关键字（产品名称或条码） */
function skuMatchesKeyword(sku: { product_name?: string | null; product_barcode?: string | null }, kw: string): boolean {
  return (sku.product_name || '').toLowerCase().includes(kw)
    || (sku.product_barcode || '').toLowerCase().includes(kw)
}

/**
 * 行内展示的 SKU：应用产品筛选时仅返回名称/条码匹配关键字的 SKU，
 * 使产品名称、数量、备注只对应搜索到的那个产品；未筛选时返回全部。
 */
function visibleSkus(item: BeileOrderRow): NonNullable<BeileOrderRow['items']> {
  const kw = appliedProduct.value.trim().toLowerCase()
  if (!kw) return item.items || []
  const matched = (item.items || []).filter((s) => skuMatchesKeyword(s, kw))
  return matched.length > 0 ? matched : (item.items || [])
}

/**
 * 客户端二次过滤：当前页订单中 product_name/barcode 模糊匹配。
 * 仅当 appliedProduct 有值时才过滤（选择建议或点击查询后生效），
 * 自由键入不触发过滤，避免输入中途表格发生抖动。
 * 匹配任一 SKU（名称或条码），而不只是订单首个产品。
 */
const displayOrders = computed<BeileOrderRow[]>(() => {
  const kw = appliedProduct.value.trim().toLowerCase()
  if (!kw) return orders.value
  return orders.value.filter((o) => {
    if ((o.product_name || '').toLowerCase().includes(kw)) return true
    return (o.items || []).some((s) => skuMatchesKeyword(s, kw))
  })
})

/** URL order_id 参数：高亮对应订单行（通知点击跳转场景） */
const route = useRoute()
const highlightId = computed<string | null>(() => {
  const oid = route.query.order_id
  return oid ? String(oid) : null
})

/** 由父组件在用户点击自动补全候选项时调用 */
function applyProductFilter(name: string) {
  appliedProduct.value = name
}

/** 由父组件在用户点击客户候选项时调用 */
function applyCustomerFilter(name: string) {
  appliedCustomer.value = name
}

function handleSearch() {
  // 点击查询按钮：将输入框当前文本确认为筛选值
  appliedProduct.value = filters.orderNo
  appliedCustomer.value = filters.customer
  refetch()
}

function handleReset() {
  filters.orderNo = ''
  filters.customer = ''
  appliedProduct.value = ''
  appliedCustomer.value = ''
  page.value = 1
  refetch()
}

function goPage(p: number) {
  page.value = p
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

// 翻页 / 筛选变化时回到列表顶部（虚拟滚动不自动归位）
watch([page, appliedProduct, appliedCustomer, confirmStatus], () => {
  virtualListRef.value?.scrollToTop()
})

/** 切换确认状态筛选并回到第一页 */
function setConfirmStatus(v: string) {
  confirmStatus.value = v
  page.value = 1
}

/** 订单详情弹窗状态 */
const detailOpen = ref(false)
const detailData = ref<BeileOrderRow | null>(null)

const detailTotalQuantity = computed(() => {
  if (!detailData.value) return 0
  const items = detailData.value.items || []
  if (items.length === 0) return detailData.value.quantity || 0
  return items.reduce((sum, s) => sum + (s.quantity || 0), 0)
})

function openDetail(item: BeileOrderRow) {
  detailData.value = item
  detailOpen.value = true
}

/** 确认中订单 id 集合（防止重复点击，按钮禁用态依赖） */
const confirmingIds = ref<Set<number>>(new Set())

const queryClient = useQueryClient()

/**
 * 确认湖北订单：仅未确认的订单记录可见按钮，确认后由后端落库
 * confirmed_at。在「未确认」筛选下成功后立即从列表移除该行并递减
 * 未确认计数，无需等待 30s 定时刷新；其他筛选下照常 refetch。
 */
async function handleConfirm(item: BeileOrderRow) {
  if (item.record_type !== 'order' || item.confirmed) return
  if (confirmingIds.value.has(item.id)) return
  confirmingIds.value.add(item.id)
  try {
    const res = await orderApi.confirmBeileOrder(item.id)
    toast.success(res.message || '订单已确认')
    if (confirmStatus.value === 'unconfirmed') {
      queryClient.setQueryData<OrderListApiResponse>(queryKey.value, (old) => {
        if (!old) return old
        const data = (old.data || []).filter((o) => o.id !== item.id)
        return {
          ...old,
          data,
          total: Math.max(0, (old.total ?? 0) - 1),
          unconfirmed_count: Math.max(0, (old.unconfirmed_count ?? 0) - 1),
        }
      })
      // 当前页被清空且不是第一页时回退一页
      if (orders.value.length === 0 && page.value > 1) {
        page.value -= 1
      }
    } else {
      await refetch()
    }
  } catch (e) {
    const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(msg || '确认订单失败')
  } finally {
    confirmingIds.value.delete(item.id)
  }
}

/**
 * 暴露给父组件（HubeiView）使用。
 * 筛选 UI 已迁移到 header 右侧，但状态与方法仍在 Tab 内统一管控。
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
})

// 已确认的客户筛选变化时回到首页
watch(() => appliedCustomer.value, () => {
  page.value = 1
})

// 每页条数变化时回到第一页
watch(perPage, () => {
  page.value = 1
})
</script>

<style scoped>
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
.bo-th,
.bo-td {
  box-sizing: border-box;
  flex: 0 0 auto;
  padding: 10px 14px;
  border-right: 1px solid #d8dce2;
  overflow: hidden;
}
.bo-th:last-child,
.bo-td:last-child {
  flex: 1 1 auto;
  min-width: 160px;
  border-right: none;
}
.bo-th {
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
.bo-th-left,
.bo-td-left {
  text-align: left !important;
  justify-content: flex-start;
}
.bo-th-right,
.bo-td-right {
  text-align: right !important;
  justify-content: flex-end;
}
.bo-th-center,
.bo-td-center {
  text-align: center !important;
  justify-content: center;
}
.bo-grid-row {
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
/* 缩略图列：紧凑内边距，容纳 56px 图 */
.bo-td-thumb {
  padding: 4px;
}
.bo-th-thumb {
  padding: 10px 6px;
  justify-content: center;
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
  justify-content: flex-start;
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

/* ===== 缩略图 blur-up（骨架屏 → 清晰图淡入） ===== */
.bo-thumb {
  position: relative;
  width: 56px;
  height: 56px;
  border-radius: 6px;
  overflow: hidden;
  background: var(--color-surface, #f3f4f6);
  flex-shrink: 0;
}
.bo-thumb-skeleton {
  position: absolute;
  inset: 0;
  z-index: 1;
  background: linear-gradient(100deg, #f1f5f9 40%, #e2e8f0 50%, #f1f5f9 60%);
  background-size: 200% 100%;
  animation: bo-shimmer 1.4s linear infinite;
  opacity: 1;
  transition: opacity 0.3s ease;
}
.bo-thumb.is-loaded .bo-thumb-skeleton {
  opacity: 0;
}
@keyframes bo-shimmer {
  0% { background-position: 120% 0; }
  100% { background-position: -120% 0; }
}
.bo-thumb-img {
  position: relative;
  z-index: 2;
  width: 100%;
  height: 100%;
  object-fit: cover;
  opacity: 0;
  transition: opacity 0.3s ease;
}
.bo-thumb.is-loaded .bo-thumb-img {
  opacity: 1;
}
.bo-thumb-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-secondary, #94a3b8);
  font-size: 16px;
  opacity: 0.6;
}

/* ===== 多 SKU 分行显示（对齐 purchase 页面风格） ===== */
.bo-td-middle {
  vertical-align: middle !important;
}
.bo-td-nowrap {
  white-space: nowrap;
}
.bo-td-right {
  text-align: right;
}
.bo-td-right .bo-sku-line {
  text-align: right;
}
.bo-row-multi-sku td {
  vertical-align: top;
}
.bo-row-clickable {
  cursor: pointer;
}

/* ===== 下单时间列：标签 + 日期（对齐 purchase） ===== */
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
.bo-barcode-text {
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 12px;
  color: var(--color-text-muted, #94a3b8);
  display: inline-block;
}

/* ===== 备注（对齐 customer-order 详情 SKU 备注样式） ===== */
.bo-sku-note {
  display: inline-block;
  color: var(--color-text-secondary);
  font-size: 12px;
  word-break: break-word;
  vertical-align: middle;
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

/* ===== 确认状态（湖北订单确认流程） ===== */
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

/* ===== 订单详情弹窗 ===== */
.bo-detail-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
  font-size: 14px;
  color: var(--color-text);
}

/* 基础信息行：一行内联展示 */
.bo-detail-meta-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 12px;
  padding: 10px 14px;
  background: #f8fafc;
  border-radius: 8px;
  font-size: 13px;
  color: var(--color-text);
}
.bo-detail-meta-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
}
.bo-detail-meta-label {
  color: var(--color-text-muted, #64748b);
  font-size: 12px;
}
.bo-detail-meta-sep {
  color: #cbd5e1;
  user-select: none;
}
.bo-detail-meta-num {
  color: var(--color-primary-700, #2d5ab8);
}

/* SKU 明细表格 */
.bo-detail-table-wrap {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  overflow: hidden;
}
.bo-detail-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.bo-detail-table thead th {
  padding: 10px 12px;
  font-weight: 600;
  font-size: 12px;
  color: #64748b;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  white-space: nowrap;
  text-align: left;
}
.bo-detail-table tbody td {
  padding: 10px 12px;
  border-bottom: 1px solid #f1f5f9;
  vertical-align: middle;
}
.bo-detail-table tbody tr:last-child td {
  border-bottom: none;
}
.bo-detail-td-name {
  font-weight: 500;
  white-space: nowrap;
}
.bo-detail-td-qty {
  text-align: right;
  font-weight: 600;
  color: var(--color-primary-700, #2d5ab8);
}
.bo-detail-td-note {
  color: var(--color-text-secondary, #475569);
  font-size: 12px;
  word-break: break-word;
}
.bo-detail-td-empty {
  text-align: center;
  color: #94a3b8;
  padding: 28px 12px !important;
}

/* 响应式 */
@media (max-width: 640px) {
  .bo-detail-meta-row { flex-direction: column; align-items: flex-start; }
  .bo-detail-meta-sep { display: none; }
}
</style>
