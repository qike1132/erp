<template>
  <div class="m-page">
    <MobileNavBar title="采购中心" :show-back="true" />
    <div class="m-page-body">
      <MFilterChips v-model="activeTab" :chips="tabChips" />

      <template v-if="activeTab === 'orders'">
        <MSearchBar v-model="keyword" placeholder="搜索订单号/产品..." @search="refetchOrders" />
        <div v-if="ordersLoading" class="m-center"><MSpinner size="lg" /></div>
        <MEmpty v-else-if="!orders?.items?.length" title="暂无采购订单" subtitle="新订单将实时推送" />
        <MList v-else header="采购中">
          <MListItem
            v-for="order in orders.items"
            :key="order.id"
            :title="`#${order.id} ${order.product_name || ''}`"
            :subtitle="`${order.supplier_name || '—'} · ${order.quantity || 0}件`"
            @click="showOrderDetail(order)"
          >
            <template #icon>
              <div class="m-icon-bg" :style="{ background: statusColor(order.status) }">
                <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" width="16" height="16"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><line x1="3" y1="6" x2="21" y2="6"/></svg>
              </div>
            </template>
            <template #value>
              <span class="m-status-badge" :style="{ color: statusColor(order.status) }">{{ statusLabel(order.status) }}</span>
            </template>
          </MListItem>
        </MList>
      </template>

      <template v-if="activeTab === 'unprocessed'">
        <div v-if="unprocessedLoading" class="m-center"><MSpinner size="lg" /></div>
        <MEmpty v-else-if="!unprocessed?.items?.length" title="暂无待审核订单" />
        <MList v-else :header="`待审核 (${unprocessed.total || 0})`">
          <MListItem
            v-for="order in unprocessed.items"
            :key="order.id"
            :title="`#${order.id} ${order.product_name || ''}`"
            :subtitle="`${order.quantity || 0}件 · ${order.customer_name || ''}`"
          >
            <template #icon>
              <div class="m-icon-bg" style="background:var(--m-accent-amber)">
                <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" width="16" height="16"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
              </div>
            </template>
          </MListItem>
        </MList>
        <button v-if="unprocessed?.items?.length" class="m-fab" @click="handleOneClick">
          <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" width="20" height="20"><polyline points="20 6 9 17 4 12"/></svg>
          一键审核
        </button>
      </template>

      <template v-if="activeTab === 'completed'">
        <MSearchBar v-model="completedKeyword" placeholder="搜索已完成订单..." />
        <div v-if="completedLoading" class="m-center"><MSpinner size="lg" /></div>
        <MEmpty v-else-if="!completedOrders?.items?.length" title="暂无已完成订单" />
        <MList v-else header="已完成">
          <MListItem
            v-for="order in completedOrders.items"
            :key="order.id"
            :title="`#${order.id} ${order.product_name || ''}`"
            :subtitle="`${order.supplier_name || '—'} · ${order.quantity || 0}件`"
          >
            <template #icon>
              <div class="m-icon-bg" style="background:var(--m-accent-emerald)">
                <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" width="16" height="16"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
              </div>
            </template>
          </MListItem>
        </MList>
      </template>
    </div>

    <MBottomSheet v-model:visible="detailVisible" :title="detailOrder ? `订单 #${detailOrder.id}` : ''">
      <div v-if="detailOrder" class="m-detail-body">
        <div class="m-detail-row"><span class="m-detail-label">产品</span><span>{{ detailOrder.product_name || '—' }}</span></div>
        <div class="m-detail-row"><span class="m-detail-label">供应商</span><span>{{ detailOrder.supplier_name || '—' }}</span></div>
        <div class="m-detail-row"><span class="m-detail-label">数量</span><span>{{ detailOrder.quantity || 0 }}</span></div>
        <div class="m-detail-row"><span class="m-detail-label">状态</span><span :style="{ color: statusColor(detailOrder.status) }">{{ statusLabel(detailOrder.status) }}</span></div>
        <div class="m-detail-row"><span class="m-detail-label">创建时间</span><span>{{ detailOrder.created_at || '—' }}</span></div>
      </div>
    </MBottomSheet>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { purchaseApi } from '@/api'
import MobileNavBar from '@/mobile/layouts/components/MobileNavBar.vue'
import MFilterChips from '@/mobile/components/MFilterChips.vue'
import MSearchBar from '@/mobile/components/MSearchBar.vue'
import MList from '@/mobile/components/MList.vue'
import MListItem from '@/mobile/components/MListItem.vue'
import MEmpty from '@/mobile/components/MEmpty.vue'
import MSpinner from '@/mobile/components/MSpinner.vue'
import MBottomSheet from '@/mobile/components/MBottomSheet.vue'

const activeTab = ref('orders')
const tabChips = [
  { label: '采购中', value: 'orders' },
  { label: '待审核', value: 'unprocessed' },
  { label: '已完成', value: 'completed' },
]

const keyword = ref('')
const completedKeyword = ref('')
const orders = ref<any>(null)
const ordersLoading = ref(false)
const unprocessed = ref<any>(null)
const unprocessedLoading = ref(false)
const completedOrders = ref<any>(null)
const completedLoading = ref(false)
const detailVisible = ref(false)
const detailOrder = ref<any>(null)

async function refetchOrders() {
  ordersLoading.value = true
  try { orders.value = await purchaseApi.orders({ page: 1, per_page: 50 }) } finally { ordersLoading.value = false }
}

async function loadUnprocessed() {
  unprocessedLoading.value = true
  try { unprocessed.value = await purchaseApi.unprocessedOrders({ page: 1, per_page: 50 }) } finally { unprocessedLoading.value = false }
}

async function loadCompleted() {
  completedLoading.value = true
  try { completedOrders.value = await purchaseApi.completedOrders({ page: 1, per_page: 50 }) } finally { completedLoading.value = false }
}

function showOrderDetail(order: any) {
  detailOrder.value = order
  detailVisible.value = true
}

async function handleOneClick() {
  const ids = (unprocessed.value?.items || []).map((o: any) => `order:${o.id}`)
  if (!ids.length) return
  try {
    await purchaseApi.oneClickGenerate({ composite_ids: ids })
    loadUnprocessed()
    refetchOrders()
  } catch { /* toast handled by request.ts */ }
}

function statusColor(s: string) {
  if (s === 'completed') return 'var(--m-accent-emerald)'
  if (s === 'pending') return 'var(--m-accent-amber)'
  if (s === 'cancelled') return 'var(--m-accent-rose)'
  return 'var(--m-text-secondary)'
}
function statusLabel(s: string) {
  const map: Record<string, string> = { completed: '已完成', pending: '待处理', processing: '采购中', cancelled: '已取消' }
  return map[s] || s || '—'
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
.m-fab { position: sticky; bottom: calc(var(--m-tabbar-safe) + 16px); left: 0; right: 0; margin: 16px auto 0; display: flex; align-items: center; justify-content: center; gap: 8px; height: 48px; padding: 0 24px; border: none; border-radius: 24px; background: var(--m-accent); color: white; font-size: 16px; font-weight: 600; cursor: pointer; box-shadow: 0 4px 14px rgba(0,113,227,0.3); font-family: inherit; -webkit-tap-highlight-color: transparent; }
.m-fab:active { transform: scale(0.95); }
.m-detail-body { display: flex; flex-direction: column; gap: 12px; }
.m-detail-row { display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 0.5px solid rgba(0,0,0,0.06); }
.m-detail-label { font-size: 14px; color: var(--m-text-secondary); }
</style>
