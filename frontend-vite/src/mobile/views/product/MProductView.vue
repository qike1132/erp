<template>
  <div class="m-product">
    <!-- Search Bar -->
    <div class="m-product-search">
      <MSearchBar v-model="searchQuery" placeholder="搜索产品名称或编号…" @search="handleSearch" />
    </div>

    <!-- Loading -->
    <MSkeleton v-if="loading" variant="list" :count="6" />

    <!-- Product List -->
    <template v-else>
      <div v-if="filteredProducts.length" class="m-product-list">
        <MCard
          v-for="product in filteredProducts"
          :key="product.id"
          clickable
          padded
          class="m-product-card"
        >
          <div class="m-product-info">
            <div class="m-product-header">
              <span class="m-product-code">{{ product.product_code }}</span>
              <MBadge v-if="product.status === 'active'" variant="success" dot>在产</MBadge>
              <MBadge v-else variant="neutral" dot>停产</MBadge>
            </div>
            <span class="m-product-name">{{ product.product_name }}</span>
            <span v-if="product.spec" class="m-product-spec">{{ product.spec }}</span>
          </div>
          <div class="m-product-arrow">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
              <polyline points="9 18 15 12 9 6" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </div>
        </MCard>
      </div>

      <MEmpty v-else :message="searchQuery ? '未找到匹配产品' : '暂无产品数据'" />
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { productApi } from '@/api'
import MCard from '@/mobile/components/MCard.vue'
import MSearchBar from '@/mobile/components/MSearchBar.vue'
import MBadge from '@/mobile/components/MBadge.vue'
import MSkeleton from '@/mobile/components/MSkeleton.vue'
import MEmpty from '@/mobile/components/MEmpty.vue'

interface Product {
  id: number
  product_code: string
  product_name: string
  spec?: string
  status?: string
}

const products = ref<Product[]>([])
const loading = ref(true)
const searchQuery = ref('')

const filteredProducts = computed(() => {
  if (!searchQuery.value) return products.value
  const q = searchQuery.value.toLowerCase()
  return products.value.filter(
    (p) =>
      p.product_code?.toLowerCase().includes(q) ||
      p.product_name?.toLowerCase().includes(q) ||
      p.spec?.toLowerCase().includes(q),
  )
})

function handleSearch(val: string) {
  searchQuery.value = val
}

async function loadProducts() {
  loading.value = true
  try {
    const res = await productApi.getList({ page: 1, page_size: 200 })
    products.value = ((res as { data?: { items?: Product[] } })?.data?.items ||
      (res as unknown as Product[])) as Product[]
  } catch (e) {
    console.error('[MProductView] load failed:', e)
    products.value = []
  } finally {
    loading.value = false
  }
}

onMounted(loadProducts)
</script>

<style scoped>
.m-product {
  padding: var(--m-gap-md);
  padding-bottom: calc(var(--m-gap-md) + var(--m-tabbar-safe));
}

.m-product-search {
  margin-bottom: var(--m-gap-md);
}

.m-product-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.m-product-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.m-product-info {
  flex: 1;
  min-width: 0;
}

.m-product-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.m-product-code {
  font-size: var(--m-font-body);
  font-weight: var(--m-font-weight-semibold);
  color: var(--m-text-primary);
  font-variant-numeric: tabular-nums;
}

.m-product-name {
  display: block;
  font-size: var(--m-font-body-sm);
  color: var(--m-text-secondary);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.m-product-spec {
  display: block;
  font-size: var(--m-font-label-sm);
  color: var(--m-text-tertiary);
  margin-top: 2px;
}

.m-product-arrow {
  color: var(--m-text-tertiary);
  flex-shrink: 0;
  margin-left: 8px;
}
</style>
