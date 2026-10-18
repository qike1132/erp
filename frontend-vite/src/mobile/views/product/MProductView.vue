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
              <span class="m-product-code">{{ product.barcode || '—' }}</span>
              <MBadge v-if="product.status !== false" variant="success" dot>在产</MBadge>
              <MBadge v-else variant="neutral" dot>停产</MBadge>
            </div>
            <span class="m-product-name">{{ product.name }}</span>
            <span v-if="product.specification" class="m-product-spec">{{ product.specification }}</span>
          </div>
          <div class="m-product-arrow">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
              <polyline points="9 18 15 12 9 6" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </div>
        </MCard>
      </div>

      <MEmpty v-else :title="searchQuery ? '未找到匹配产品' : '暂无产品数据'" />

      <UiPagination
        v-if="totalItems > MOBILE_LIST_PAGE_SIZE"
        :current-page="page"
        :total-pages="Math.ceil(totalItems / MOBILE_LIST_PAGE_SIZE)"
        :total-items="totalItems"
        @update:current-page="(p: number) => { page = p; loadProducts() }"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { productApi } from '@/api'
import { MOBILE_LIST_PAGE_SIZE } from '@/mobile/constants'
import type { Product } from '@/types'
import MCard from '@/mobile/components/MCard.vue'
import MSearchBar from '@/mobile/components/MSearchBar.vue'
import MBadge from '@/mobile/components/MBadge.vue'
import MSkeleton from '@/mobile/components/MSkeleton.vue'
import MEmpty from '@/mobile/components/MEmpty.vue'
import { showToast } from '@/composables/useToast'

const products = ref<Product[]>([])
const loading = ref(true)
const searchQuery = ref('')
const page = ref(1)
const totalItems = ref(0)

// F-FE-MOBILE-07 后本地过滤已冗余（搜索走服务端 search，含 name/barcode/spec
// ilike），保留 computed 仅作切页时的即时过滤——与后端口径一致，不再自带
// specification 分支之外的额外语义。
const filteredProducts = computed(() => products.value)

function handleSearch(val: string) {
  searchQuery.value = val
  page.value = 1 // 2026-10-17 审计 AUD-22：搜索必须回到第 1 页
  loadProducts()
}

async function loadProducts() {
  loading.value = true
  try {
    // F-FE-MOBILE-07：服务端搜索；AUD-22：服务端分页（此前固定 page=1，
    // 第 201 条起永久不可达）
    const res = await productApi.list({ page: page.value, per_page: MOBILE_LIST_PAGE_SIZE, search: searchQuery.value })
    products.value = res.items ?? []
    totalItems.value = res.total ?? 0
  } catch (e) {
    console.error('[MProductView] load failed:', e)
    // 2026-10-18 OCR 评审：失败时不要把 totalItems 归零——分页器会消失，
    // 用户被困在空列表且无页码可回。保留旧总数并提示，由用户重试。
    showToast('产品加载失败，请重试', 'error')
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
