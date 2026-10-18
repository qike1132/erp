<template>
  <div class="m-page">
    <MobileNavBar title="订单查询" :show-back="true" />
    <div class="m-page-body">
      <MFilterChips v-model="activeTab" :chips="tabChips" />

      <MSearchBar v-model="keyword" placeholder="搜索订单号/产品/客户..." @search="onSearch" />

      <div v-if="loading" class="m-center"><MSpinner size="lg" /></div>
      <MEmpty v-else-if="!orders.length" title="暂无订单" subtitle="输入关键词搜索" />
      <MList v-else>
        <MListItem v-for="o in orders" :key="o.id" :title="`#${o.order_no || o.id} ${o.product?.name || ''}`" :subtitle="`${o.customer || '—'} · ${o.quantity || 0}件 · ${o.order_date || ''}`">
          <template #icon>
            <div class="m-icon-bg" :style="{ background: orderColor(o.status) }">
              <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" width="16" height="16"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z" /><line x1="3" y1="6" x2="21" y2="6" /></svg>
            </div>
          </template>
          <template #value>
            <span class="m-badge" :style="{ color: orderColor(o.status), background: orderBg(o.status) }">{{ orderLabel(o.status) }}</span>
          </template>
        </MListItem>
      </MList>

      <UiPagination
        v-if="total > perPage"
        :current-page="page"
        :total-pages="Math.ceil(total / perPage)"
        :total-items="total"
        @update:current-page="page = $event"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { orderApi } from '@/api'
import MobileNavBar from '@/mobile/layouts/components/MobileNavBar.vue'
import MFilterChips from '@/mobile/components/MFilterChips.vue'
import MSearchBar from '@/mobile/components/MSearchBar.vue'
import MList from '@/mobile/components/MList.vue'
import MListItem from '@/mobile/components/MListItem.vue'
import MEmpty from '@/mobile/components/MEmpty.vue'
import MSpinner from '@/mobile/components/MSpinner.vue'
import { showToast } from '@/composables/useToast'

const activeTab = ref('all')
// 2026-10-17 审计 AUD-20：筛选值必须是后端中文状态（shared_models/order.py
// VALID_ORDER_STATUSES）。此前用 pending/completed 等英文键，/orders/list
// 会按等值匹配直接返回空列表——状态筛选 100% 失效且用户无任何反馈。
const tabChips = [
  { label: '全部', value: 'all' },
  { label: '待备货', value: '待备货' },
  { label: '部分备货', value: '部分备货' },
  { label: '已备货', value: '已备货' },
  { label: '待出货', value: '待出货' },
  { label: '已出货', value: '已出货' },
  { label: '批次已完成', value: '批次已完成' },
  { label: '已取消', value: '已取消' },
]
const keyword = ref('')
// 字段与后端 OrderSerializer.LIST_CONFIG 对齐（F-FE-MOBILE-02：原先读
// product_name/customer_name/date 等后端不返回的键，副标题恒为空）
const orders = ref<Array<{ id: number; order_no?: string; customer?: string; order_date?: string; quantity?: number; status?: string; product?: { name?: string } }>>([])
const loading = ref(false)
const page = ref(1)
const perPage = 20
const total = ref(0)

async function handleSearch() {
  loading.value = true
  try {
    const res = await orderApi.list({ keyword: keyword.value, status: activeTab.value === 'all' ? '' : activeTab.value, page: page.value, per_page: perPage })
    orders.value = res?.data || []
    total.value = res?.total || 0
  } catch {
    // 此前无 catch：请求失败时列表静默保持旧数据（或空白），用户零感知。
    // 2026-10-18 OCR 评审：保留 total（分页器不消失），仅清空列表并提示。
    orders.value = []
    showToast('订单查询失败，请重试', 'error')
  } finally { loading.value = false }
}

// 2026-10-18 OCR 评审：切换状态/提交搜索都必须回到第 1 页，
// 否则会带着旧页码查询，出现空页或越界。
watch(activeTab, () => {
  page.value = 1
})
watch([activeTab, page], handleSearch)
onMounted(handleSearch)

function onSearch() {
  // 2026-10-18 OCR 评审：页码变化由 watch([activeTab, page]) 触发；
  // 仅在已是第 1 页时手动重查，避免同一参数发两次请求。
  if (page.value === 1) handleSearch()
  else page.value = 1
}

function orderColor(s: string | undefined) {
  if (s === '已出货' || s === '批次已完成') return 'var(--m-accent-emerald)'
  if (s === '待备货' || s === '部分备货') return 'var(--m-accent-amber)'
  if (s === '已取消') return 'var(--m-accent-rose)'
  return 'var(--m-accent)'
}
function orderBg(s: string | undefined) {
  if (s === '已出货' || s === '批次已完成') return 'rgba(48,209,88,0.1)'
  if (s === '待备货' || s === '部分备货') return 'rgba(255,149,0,0.1)'
  if (s === '已取消') return 'rgba(255,45,85,0.1)'
  return 'rgba(0,113,227,0.1)'
}
function orderLabel(s: string | undefined) {
  // 后端状态本身即中文展示文案；未知值原样显示，不再维护第二套映射
  return s || '—'
}
</script>

<style scoped>
.m-page { display: flex; flex-direction: column; height: 100%; background: var(--m-bg-deep); }
.m-page-body { flex: 1; min-height: 0; overflow-y: auto; padding: var(--m-gap-md); padding-bottom: calc(var(--m-gap-lg) + var(--m-tabbar-safe)); -webkit-overflow-scrolling: touch; }
.m-center { display: flex; justify-content: center; padding: 48px 0; }
.m-icon-bg { width: 100%; height: 100%; border-radius: 8px; display: flex; align-items: center; justify-content: center; }
.m-badge { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 10px; }
</style>
