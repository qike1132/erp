<template>
  <div class="m-page">
    <MobileNavBar title="订单查询" :show-back="true" />
    <div class="m-page-body">
      <MFilterChips v-model="activeTab" :chips="tabChips" />

      <MSearchBar v-model="keyword" placeholder="搜索订单号/产品/客户..." @search="handleSearch" />

      <div v-if="loading" class="m-center"><MSpinner size="lg" /></div>
      <MEmpty v-else-if="!orders.length" title="暂无订单" subtitle="输入关键词搜索" />
      <MList v-else>
        <MListItem v-for="o in orders" :key="o.id" :title="`#${o.id} ${o.product_name || ''}`" :subtitle="`${o.customer_name || '—'} · ${o.quantity || 0}件 · ${o.date || ''}`">
          <template #icon>
            <div class="m-icon-bg" :style="{ background: orderColor(o.status) }">
              <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" width="16" height="16"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><line x1="3" y1="6" x2="21" y2="6"/></svg>
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

const activeTab = ref('all')
const tabChips = [{ label: '全部', value: 'all' }, { label: '待处理', value: 'pending' }, { label: '已完成', value: 'completed' }]
const keyword = ref('')
const orders = ref<Array<{ id: number; product_name?: string; customer_name?: string; quantity?: number; date?: string; status?: string }>>([])
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
  } finally { loading.value = false }
}

watch([activeTab, page], handleSearch)
onMounted(handleSearch)

function orderColor(s: string | undefined) {
  if (s === 'completed' || s === 'done') return 'var(--m-accent-emerald)'
  if (s === 'pending') return 'var(--m-accent-amber)'
  if (s === 'cancelled') return 'var(--m-accent-rose)'
  return 'var(--m-accent)'
}
function orderBg(s: string | undefined) {
  if (s === 'completed' || s === 'done') return 'rgba(48,209,88,0.1)'
  if (s === 'pending') return 'rgba(255,149,0,0.1)'
  if (s === 'cancelled') return 'rgba(255,45,85,0.1)'
  return 'rgba(0,113,227,0.1)'
}
function orderLabel(s: string | undefined) {
  const map: Record<string, string> = { pending: '待处理', processing: '处理中', completed: '已完成', done: '已完成', cancelled: '已取消' }
  return (s && map[s]) || s || '—'
}
</script>

<style scoped>
.m-page { display: flex; flex-direction: column; height: 100%; background: var(--m-bg-deep); }
.m-page-body { flex: 1; min-height: 0; overflow-y: auto; padding: var(--m-gap-md); padding-bottom: calc(var(--m-gap-lg) + var(--m-tabbar-safe)); -webkit-overflow-scrolling: touch; }
.m-center { display: flex; justify-content: center; padding: 48px 0; }
.m-icon-bg { width: 100%; height: 100%; border-radius: 8px; display: flex; align-items: center; justify-content: center; }
.m-badge { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 10px; }
</style>
