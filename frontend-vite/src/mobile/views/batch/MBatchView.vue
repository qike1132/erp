<template>
  <div class="m-page">
    <MobileNavBar title="批次号查询" :show-back="true" />
    <div class="m-page-body">
      <MSearchBar v-model="keyword" placeholder="搜索批次号/产品/客户..." @search="resetAndSearch" />

      <MFilterChips v-model="statusFilter" :chips="statusChips" />

      <div v-if="loading" class="m-center"><MSpinner size="lg" /></div>
      <MEmpty v-else-if="!groups.length" title="暂无批次数据" subtitle="输入关键词搜索" />

      <div v-else class="m-batch-groups">
        <div v-for="group in groups" :key="group.key" class="m-batch-group">
          <div class="m-group-header">
            <div class="m-group-customer">{{ group.customer }}</div>
            <div class="m-group-count">{{ group.items?.length || 0 }}条</div>
          </div>
          <MList>
            <MListItem
              v-for="item in group.items"
              :key="item.id"
              :title="item.product_name || '—'"
              :subtitle="`批次: ${item.batch_no || '未分配'} · ${item.quantity || 0}件`"
            >
              <template #value>
                <span class="m-batch-status" :style="{ color: batchColor(item.status) }">{{ batchLabel(item.status) }}</span>
              </template>
            </MListItem>
          </MList>
        </div>
      </div>

      <UiPagination
        v-if="totalItems > MOBILE_PAGE_SIZE"
        :current-page="page"
        :total-pages="Math.ceil(totalItems / MOBILE_PAGE_SIZE)"
        :total-items="totalItems"
        @update:current-page="(p: number) => { page = p; handleSearch() }"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { batchApi } from '@/api'
import { MOBILE_PAGE_SIZE } from '@/mobile/constants'
import type { BatchQueryItem } from '@/types'
import MobileNavBar from '@/mobile/layouts/components/MobileNavBar.vue'
import MSearchBar from '@/mobile/components/MSearchBar.vue'
import MFilterChips from '@/mobile/components/MFilterChips.vue'
import MList from '@/mobile/components/MList.vue'
import MListItem from '@/mobile/components/MListItem.vue'
import MEmpty from '@/mobile/components/MEmpty.vue'
import MSpinner from '@/mobile/components/MSpinner.vue'

// 2026-10-17 审计 P2-65：后端 BatchQueryItem 不返回 order_id，此前前端扩展的
// 幽灵字段永远 undefined（已随 item-key 修正一并移除）
type BatchItem = BatchQueryItem

const keyword = ref('')
const statusFilter = ref('all')
const statusChips = [
  { label: '全部', value: 'all' },
  { label: '待备货', value: 'pending' },
  { label: '已备货', value: 'stocked' },
  { label: '已出货', value: 'shipped' },
]
const rawList = ref<BatchItem[]>([])
const loading = ref(false)
const page = ref(1)
const totalItems = ref(0)

const groups = computed(() => {
  // 后端返回的是扁平 BatchQueryItem[]，按客户分组以保留原 UI 结构
  const map = new Map<string, { key: string; customer: string; items: BatchItem[] }>()
  for (const item of rawList.value) {
    const key = item.customer || '未知客户'
    if (!map.has(key)) map.set(key, { key, customer: key, items: [] })
    map.get(key)!.items.push(item)
  }
  return Array.from(map.values())
})

async function handleSearch() {
  loading.value = true
  try {
    // 2026-10-17 审计 AUD-22：服务端分页（此前固定 page=1，第 51 条起不可达）
    const res = await batchApi.list({
      keyword: keyword.value,
      status: statusFilter.value === 'all' ? '' : statusFilter.value,
      page: page.value,
      per_page: MOBILE_PAGE_SIZE,
    })
    rawList.value = res?.data || []
    totalItems.value = res?.total ?? 0
  } finally { loading.value = false }
}

// 状态切换必须回到第 1 页；搜索词由搜索框显式提交（避免逐字符请求）
function resetAndSearch() {
  page.value = 1
  handleSearch()
}

watch(statusFilter, resetAndSearch)

onMounted(handleSearch)

function batchColor(s: string | null | undefined) {
  if (s === 'shipped') return 'var(--m-accent-emerald)'
  if (s === 'stocked') return 'var(--m-accent)'
  if (s === 'partial') return 'var(--m-accent-amber)'
  return 'var(--m-text-secondary)'
}
function batchLabel(s: string | null | undefined) {
  const map: Record<string, string> = { pending: '待备货', partial: '部分备货', stocked: '已备货', shipped: '已出货', completed: '已完成' }
  return (s && map[s]) || s || '—'
}
</script>

<style scoped>
.m-page { display: flex; flex-direction: column; height: 100%; background: var(--m-bg-deep); }
.m-page-body { flex: 1; min-height: 0; overflow-y: auto; padding: var(--m-gap-md); padding-bottom: calc(var(--m-gap-lg) + var(--m-tabbar-safe)); -webkit-overflow-scrolling: touch; }
.m-center { display: flex; justify-content: center; padding: 48px 0; }
.m-batch-groups { display: flex; flex-direction: column; gap: 16px; }
.m-batch-group { }
.m-group-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.m-group-customer { font-size: 15px; font-weight: 600; color: var(--m-text-primary); }
.m-group-count { font-size: 12px; color: var(--m-text-secondary); }
.m-batch-status { font-size: 12px; font-weight: 600; }
</style>
