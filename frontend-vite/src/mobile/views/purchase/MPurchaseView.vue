<template>
  <div class="m-page">
    <MobileNavBar title="采购中心" :show-back="true" />
    <div class="m-page-body">
      <MFilterChips v-model="activeTab" :chips="tabChips" />

      <template v-if="activeTab === 'orders'">
        <MSearchBar v-model="keyword" placeholder="搜索订单号/产品..." @search="() => refetchOrders()" />
        <div v-if="ordersLoading" class="m-center"><MSpinner size="lg" /></div>
        <MEmpty v-else-if="!orders?.orders?.length" title="暂无采购订单" subtitle="新订单将实时推送" />
        <MList v-else header="采购中">
          <MListItem
            v-for="order in orders.orders"
            :key="order.id"
            :title="`#${order.id} ${order.product_name || ''}`"
            :subtitle="`${order.supplier_name || '—'} · ${order.quantity || 0}件`"
            @click="showOrderDetail(order)"
          >
            <template #icon>
              <div class="m-icon-bg" :style="{ background: statusColor(order.status) }">
                <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" width="16" height="16"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z" /><line x1="3" y1="6" x2="21" y2="6" /></svg>
              </div>
            </template>
            <template #value>
              <span class="m-status-badge" :style="{ color: statusColor(order.status) }">{{ statusLabel(order.status) }}</span>
            </template>
          </MListItem>
        </MList>
        <UiPagination
          v-if="(orders?.total || 0) > MOBILE_PAGE_SIZE"
          :current-page="ordersPage"
          :total-pages="Math.ceil((orders?.total || 0) / MOBILE_PAGE_SIZE)"
          :total-items="orders?.total || 0"
          @update:current-page="(p: number) => { ordersPage = p; refetchOrders(p) }"
        />
      </template>

      <template v-if="activeTab === 'unprocessed'">
        <div v-if="unprocessedLoading" class="m-center"><MSpinner size="lg" /></div>
        <MEmpty v-else-if="!unprocessed?.orders?.length" title="暂无待生成订单" subtitle="未配置BOM的订单无法下单" />
        <MList v-else :header="`待生成 (${unprocessed.total || 0})`">
          <MListItem
            v-for="order in unprocessed.orders"
            :key="order.id"
            :title="`#${order.id} ${order.product_name || ''}`"
            :subtitle="`${order.quantity || 0}件 · ${order.customer || ''}${order.has_bom === false ? ' · 未配置BOM，无法下单' : ''}`"
          >
            <template #icon>
              <div class="m-icon-bg" style="background:var(--m-accent-amber)">
                <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" width="16" height="16"><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg>
              </div>
            </template>
          </MListItem>
        </MList>
        <UiPagination
          v-if="(unprocessed?.total || 0) > MOBILE_PAGE_SIZE"
          :current-page="unprocessedPage"
          :total-pages="Math.ceil((unprocessed?.total || 0) / MOBILE_PAGE_SIZE)"
          :total-items="unprocessed?.total || 0"
          @update:current-page="(p: number) => { unprocessedPage = p; loadUnprocessed(p) }"
        />
      </template>

      <template v-if="activeTab === 'completed'">
        <MSearchBar v-model="completedKeyword" placeholder="搜索已完成订单..." @search="searchCompleted" />
        <div v-if="completedLoading" class="m-center"><MSpinner size="lg" /></div>
        <MEmpty v-else-if="!completedOrders?.orders?.length" title="暂无已完成订单" />
        <MList v-else header="已完成">
          <MListItem
            v-for="order in completedOrders.orders"
            :key="order.id"
            :title="`#${order.id} ${order.product_name || ''}`"
            :subtitle="`${order.supplier_name || '—'} · ${order.quantity || 0}件`"
          >
            <template #icon>
              <div class="m-icon-bg" style="background:var(--m-accent-emerald)">
                <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" width="16" height="16"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" /></svg>
              </div>
            </template>
          </MListItem>
        </MList>
        <UiPagination
          v-if="(completedOrders?.total || 0) > MOBILE_PAGE_SIZE"
          :current-page="completedPage"
          :total-pages="Math.ceil((completedOrders?.total || 0) / MOBILE_PAGE_SIZE)"
          :total-items="completedOrders?.total || 0"
          @update:current-page="(p: number) => { completedPage = p; loadCompleted(p) }"
        />
      </template>
    </div>

    <MBottomSheet v-model:visible="detailVisible" :title="detailOrder ? `订单 #${detailOrder.id}` : ''">
      <div v-if="detailOrder" class="m-detail-body">
        <div class="m-detail-row"><span class="m-detail-label">产品</span><span>{{ detailOrder.product_name || '—' }}</span></div>
        <div class="m-detail-row"><span class="m-detail-label">供应商</span><span>{{ detailSupplier }}</span></div>
        <div class="m-detail-row"><span class="m-detail-label">数量</span><span>{{ detailOrder.quantity || 0 }}</span></div>
        <div class="m-detail-row"><span class="m-detail-label">状态</span><span :style="{ color: statusColor(detailOrder.status) }">{{ statusLabel(detailOrder.status) }}</span></div>
        <div class="m-detail-row"><span class="m-detail-label">创建时间</span><span>{{ detailTime }}</span></div>
      </div>
    </MBottomSheet>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { purchaseApi } from '@/api'
import { MOBILE_PAGE_SIZE } from '@/mobile/constants'
import type { PurchaseOrder, UnprocessedOrder } from '@/types'
import MobileNavBar from '@/mobile/layouts/components/MobileNavBar.vue'
import MFilterChips from '@/mobile/components/MFilterChips.vue'
import MSearchBar from '@/mobile/components/MSearchBar.vue'
import MList from '@/mobile/components/MList.vue'
import MListItem from '@/mobile/components/MListItem.vue'
import MEmpty from '@/mobile/components/MEmpty.vue'
import MSpinner from '@/mobile/components/MSpinner.vue'
import MBottomSheet from '@/mobile/components/MBottomSheet.vue'
import { showToast } from '@/composables/useToast'

const activeTab = ref('orders')
const tabChips = [
  { label: '采购中', value: 'orders' },
  { label: '待生成', value: 'unprocessed' },
  { label: '已完成', value: 'completed' },
]

const keyword = ref('')
const completedKeyword = ref('')
// F-FE-MOBILE-05：读 total + 翻页（原先恒第 1 页，第 51 条起在移动端不可达）
const ordersPage = ref(1)
const unprocessedPage = ref(1)
const completedPage = ref(1)

// 列表响应类型由 API 层签名推导，移动端不再自行声明后端 DTO（S12）
type PurchaseOrderList = Awaited<ReturnType<typeof purchaseApi.orders>>
type UnprocessedOrderList = Awaited<ReturnType<typeof purchaseApi.unprocessedOrders>>
// completed 接口的响应体没有 current_page（多一个 total_pages），单独取签名
type CompletedOrderList = Awaited<ReturnType<typeof purchaseApi.completed>>

const orders = ref<PurchaseOrderList | null>(null)
const ordersLoading = ref(false)
const unprocessed = ref<UnprocessedOrderList | null>(null)
const unprocessedLoading = ref(false)
const completedOrders = ref<CompletedOrderList | null>(null)
const completedLoading = ref(false)
const detailVisible = ref(false)
const detailOrder = ref<PurchaseOrder | UnprocessedOrder | null>(null)

/** 待审核订单（UnprocessedOrder）没有供应商字段，详情页显示占位符。 */
const detailSupplier = computed(() =>
  detailOrder.value && 'supplier_name' in detailOrder.value ? detailOrder.value.supplier_name || '—' : '—',
)

/** 采购单用 create_time，待审核订单用 order_date（DTO 字段名不同，统一在此收敛）。 */
const detailTime = computed(() => {
  const order = detailOrder.value
  if (!order) return '—'
  if ('create_time' in order && order.create_time) return order.create_time
  return order.order_date || '—'
})

async function refetchOrders(page = 1) {
  const prev = ordersPage.value
  ordersPage.value = page
  ordersLoading.value = true
  try { orders.value = await purchaseApi.orders({ page, per_page: MOBILE_PAGE_SIZE, keyword: keyword.value }) }
  catch { ordersPage.value = prev; showToast('订单加载失败，请重试', 'error') }
  finally { ordersLoading.value = false }
}

async function loadUnprocessed(page = 1) {
  // 注：/unprocessed-orders 端点无 keyword 参数（审计 F-FE-MOBILE-04 仅
  // 采购中/已完成两个页签的后端支持搜索），此页签搜索待端点增强后接线。
  const prev = unprocessedPage.value
  unprocessedPage.value = page
  unprocessedLoading.value = true
  try { unprocessed.value = await purchaseApi.unprocessedOrders({ page, per_page: MOBILE_PAGE_SIZE }) }
  catch { unprocessedPage.value = prev; showToast('待生成订单加载失败，请重试', 'error') }
  finally { unprocessedLoading.value = false }
}

async function loadCompleted(page = 1) {
  const prev = completedPage.value
  completedPage.value = page
  completedLoading.value = true
  try { completedOrders.value = await purchaseApi.completed({ page, per_page: MOBILE_PAGE_SIZE, keyword: completedKeyword.value }) }
  catch { completedPage.value = prev; showToast('已完成订单加载失败，请重试', 'error') }
  finally { completedLoading.value = false }
}

/** 搜索已完成订单：重置到第 1 页（否则会在旧页码上检索，结果为空） */
function searchCompleted() {
  loadCompleted(1)
}

function showOrderDetail(order: PurchaseOrder | UnprocessedOrder) {
  detailOrder.value = order
  detailVisible.value = true
}

function statusColor(s: string | undefined) {
  if (s === 'completed') return 'var(--m-accent-emerald)'
  if (s === 'pending') return 'var(--m-accent-amber)'
  if (s === 'cancelled') return 'var(--m-accent-rose)'
  return 'var(--m-text-secondary)'
}
function statusLabel(s: string | undefined) {
  const map: Record<string, string> = { completed: '已完成', pending: '待处理', processing: '采购中', cancelled: '已取消' }
  return (s && map[s]) || s || '—'
}

refetchOrders()
loadUnprocessed()
loadCompleted()
</script>

<style scoped>
.m-page { display: flex; flex-direction: column; height: 100%; background: var(--m-bg-deep); }
.m-page-body { flex: 1; min-height: 0; overflow-y: auto; padding: var(--m-gap-md); padding-bottom: calc(var(--m-gap-lg) + var(--m-tabbar-safe)); -webkit-overflow-scrolling: touch; }
.m-center { display: flex; justify-content: center; padding: 48px 0; }
.m-icon-bg { width: 100%; height: 100%; border-radius: 8px; display: flex; align-items: center; justify-content: center; }
.m-status-badge { font-size: 12px; font-weight: 600; }
.m-detail-body { display: flex; flex-direction: column; gap: 12px; }
.m-detail-row { display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 0.5px solid rgba(0,0,0,0.06); }
.m-detail-label { font-size: 14px; color: var(--m-text-secondary); }
</style>
