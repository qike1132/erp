<template>
  <div class="m-stock">
    <!-- Search Bar -->
    <div class="m-stock-search">
      <MSearchBar v-model="searchQuery" placeholder="搜索物料名称或编码…" />
    </div>

    <!-- Filter Tabs -->
    <MFilterChips
      v-model="selectedTab"
      :options="tabOptions"
      class="m-stock-tabs"
    />

    <!-- Loading -->
    <MSkeleton v-if="loading" variant="list" :count="5" />

    <!-- Stock List -->
    <template v-else>
      <div v-if="filteredStock.length" class="m-stock-list">
        <MCard
          v-for="item in filteredStock"
          :key="item.id"
          clickable
          padded
          class="m-stock-card"
        >
          <div class="m-stock-main">
            <div class="m-stock-info">
              <span class="m-stock-name">{{ item.material_name || item.product_name }}</span>
              <span class="m-stock-code">{{ item.material_code || item.product_code }}</span>
            </div>
            <div class="m-stock-qty">
              <span :class="['m-stock-qty-val', getQtyClass(item)]">
                {{ formatQty(item.quantity) }}
              </span>
              <span class="m-stock-qty-unit">{{ item.unit || '个' }}</span>
            </div>
          </div>
          <div v-if="item.warehouse_name" class="m-stock-meta">
            <span class="m-stock-warehouse">{{ item.warehouse_name }}</span>
            <MBadge v-if="isLowStock(item)" variant="warning" dot>低库存</MBadge>
          </div>
        </MCard>
      </div>

      <MEmpty v-else :message="searchQuery ? '未找到匹配物料' : '暂无库存数据'" />
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { stockApi } from '@/api'
import MCard from '@/mobile/components/MCard.vue'
import MSearchBar from '@/mobile/components/MSearchBar.vue'
import MFilterChips from '@/mobile/components/MFilterChips.vue'
import MBadge from '@/mobile/components/MBadge.vue'
import MSkeleton from '@/mobile/components/MSkeleton.vue'
import MEmpty from '@/mobile/components/MEmpty.vue'

interface StockItem {
  id: number
  product_code?: string
  product_name?: string
  material_code?: string
  material_name?: string
  quantity: number
  unit?: string
  warehouse_name?: string
  safety_stock?: number
}

const stockItems = ref<StockItem[]>([])
const loading = ref(true)
const searchQuery = ref('')
const selectedTab = ref('all')

const tabOptions = [
  { key: 'all', label: '全部' },
  { key: 'active', label: '在库' },
  { key: 'low', label: '低库存' },
]

const filteredStock = computed(() => {
  let items = stockItems.value

  if (selectedTab.value === 'low') {
    items = items.filter((i) => isLowStock(i))
  } else if (selectedTab.value === 'active') {
    items = items.filter((i) => (i.quantity ?? 0) > (i.safety_stock ?? 0))
  }

  if (searchQuery.value) {
    const q = searchQuery.value.toLowerCase()
    items = items.filter(
      (i) =>
        (i.material_name ?? i.product_name ?? '').toLowerCase().includes(q) ||
        (i.material_code ?? i.product_code ?? '').toLowerCase().includes(q),
    )
  }

  return items
})

function formatQty(val: number | null | undefined): string {
  if (val == null) return '0'
  return Number(val).toLocaleString('zh-CN')
}

function isLowStock(item: StockItem): boolean {
  return (item.quantity ?? 0) <= (item.safety_stock ?? 0)
}

function getQtyClass(item: StockItem): string {
  if (isLowStock(item)) return 'low'
  if ((item.quantity ?? 0) > 1000) return 'high'
  return ''
}

async function loadStock() {
  loading.value = true
  try {
    const res = await stockApi.getList({ page: 1, page_size: 200 })
    stockItems.value = ((res as { data?: { items?: StockItem[] } })?.data?.items ||
      (res as unknown as StockItem[])) as StockItem[]
  } catch (e) {
    console.error('[MStockView] load failed:', e)
    stockItems.value = []
  } finally {
    loading.value = false
  }
}

onMounted(loadStock)
</script>

<style scoped>
.m-stock {
  padding: var(--m-gap-md);
  padding-bottom: calc(var(--m-gap-md) + var(--m-tabbar-safe));
}

.m-stock-search {
  margin-bottom: var(--m-gap-sm);
}

.m-stock-tabs {
  margin-bottom: var(--m-gap-md);
}

.m-stock-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.m-stock-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.m-stock-info {
  flex: 1;
  min-width: 0;
}

.m-stock-name {
  display: block;
  font-size: var(--m-font-body-lg);
  font-weight: var(--m-font-weight-semibold);
  color: var(--m-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.m-stock-code {
  display: block;
  font-size: var(--m-font-body-sm);
  color: var(--m-text-tertiary);
  margin-top: 2px;
}

.m-stock-qty {
  display: flex;
  align-items: baseline;
  gap: 4px;
  flex-shrink: 0;
  margin-left: 12px;
}

.m-stock-qty-val {
  font-size: 20px;
  font-weight: 700;
  color: var(--m-text-primary);
  font-variant-numeric: tabular-nums;
}

.m-stock-qty-val.low {
  color: var(--m-accent-red);
}
.m-stock-qty-val.high {
  color: var(--m-accent);
}

.m-stock-qty-unit {
  font-size: var(--m-font-label-sm);
  color: var(--m-text-tertiary);
}

.m-stock-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: var(--m-border-subtle);
}

.m-stock-warehouse {
  font-size: var(--m-font-label-sm);
  color: var(--m-text-secondary);
}
</style>
