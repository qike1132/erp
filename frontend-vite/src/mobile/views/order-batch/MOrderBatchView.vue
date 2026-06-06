<template>
  <div class="m-page">
    <MobileNavBar title="订单流水" :show-back="true" />
    <div class="m-page-body">
      <MSearchBar v-model="keyword" placeholder="搜索订单号/产品..." @search="handleSearch" />

      <MFilterChips v-model="customerFilter" :chips="customerChips" />

      <div v-if="loading" class="m-center"><MSpinner size="lg" /></div>
      <MEmpty v-else-if="!orders.length" title="暂无订单流水" />

      <div v-else class="m-order-groups">
        <div v-for="group in displayGroups" :key="group.key" class="m-order-group">
          <div class="m-group-header">
            <span class="m-group-title">{{ group.customer || group.key }}</span>
            <span class="m-group-count">{{ group.items?.length || 0 }}条</span>
          </div>
          <MList>
            <MListItem
              v-for="item in group.items"
              :key="item.id || item.order_id"
              :title="item.product_name || '—'"
              :subtitle="`批次: ${item.batch_no || '—'} · ${item.quantity || 0}件`"
            >
              <template #value>
                <span class="m-time">{{ (item.created_at || item.date || '').slice(0, 10) }}</span>
              </template>
            </MListItem>
          </MList>
        </div>
      </div>

      <div v-if="total > perPage" class="m-pagination">
        <button class="m-page-btn" :disabled="page <= 1" @click="page--">上一页</button>
        <span>{{ page }} / {{ Math.ceil(total / perPage) }}</span>
        <button class="m-page-btn" :disabled="page >= Math.ceil(total / perPage)" @click="page++">下一页</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { orderBatchApi, customerApi } from '@/api'
import MobileNavBar from '@/mobile/layouts/components/MobileNavBar.vue'
import MSearchBar from '@/mobile/components/MSearchBar.vue'
import MFilterChips from '@/mobile/components/MFilterChips.vue'
import MList from '@/mobile/components/MList.vue'
import MListItem from '@/mobile/components/MListItem.vue'
import MEmpty from '@/mobile/components/MEmpty.vue'
import MSpinner from '@/mobile/components/MSpinner.vue'

const keyword = ref('')
const customerFilter = ref('all')
const customerChips = ref([{ label: '全部', value: 'all' }])
const orders = ref<any[]>([])
const loading = ref(false)
const page = ref(1)
const perPage = 20
const total = ref(0)

const displayGroups = computed(() => {
  const map = new Map<string, any[]>()
  for (const o of orders.value) {
    const key = o.customer_name || o.customer || '其他'
    if (!map.has(key)) map.set(key, [])
    map.get(key)!.push(o)
  }
  return Array.from(map.entries()).map(([key, items]) => ({ key, customer: key, items }))
})

async function loadCustomers() {
  try {
    const names = await customerApi.activeNames()
    if (names?.length) {
      customerChips.value = [{ label: '全部', value: 'all' }, ...names.slice(0, 5).map((n: string) => ({ label: n, value: n }))]
    }
  } catch { /* */ }
}

async function handleSearch() {
  loading.value = true
  try {
    const res = await orderBatchApi.orders({
      keyword: keyword.value,
      customer: customerFilter.value === 'all' ? '' : customerFilter.value,
      page: page.value,
      per_page: perPage,
    })
    orders.value = res?.items || []
    total.value = res?.total || 0
  } finally { loading.value = false }
}

onMounted(() => { loadCustomers(); handleSearch() })
</script>

<style scoped>
.m-page { display: flex; flex-direction: column; height: 100%; background: var(--m-bg-deep); }
.m-page-body { flex: 1; min-height: 0; overflow-y: auto; padding: var(--m-gap-md); padding-bottom: calc(var(--m-gap-lg) + var(--m-tabbar-safe)); -webkit-overflow-scrolling: touch; }
.m-center { display: flex; justify-content: center; padding: 48px 0; }
.m-order-groups { display: flex; flex-direction: column; gap: 16px; }
.m-group-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.m-group-title { font-size: 15px; font-weight: 600; color: var(--m-text-primary); }
.m-group-count { font-size: 12px; color: var(--m-text-secondary); }
.m-time { font-size: 12px; color: var(--m-text-tertiary); }
.m-pagination { display: flex; justify-content: center; align-items: center; gap: 12px; margin-top: 16px; font-size: 13px; color: var(--m-text-secondary); }
.m-page-btn { padding: 6px 14px; border: 1px solid rgba(0,0,0,0.08); border-radius: 8px; background: var(--m-bg-surface); font-size: 13px; cursor: pointer; font-family: inherit; }
.m-page-btn:disabled { opacity: 0.4; }
</style>
