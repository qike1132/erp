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

      <MEmpty v-else-if="loadError" :title="loadError">
        <template v-if="loadErrorRetryable" #action>
          <button
            type="button"
            style="margin-top: 12px; padding: 8px 18px; border-radius: 8px; border: 1px solid var(--m-border, #dbe3ef); background: #fff; font: inherit;"
            @click="loadProducts()"
          >重试</button>
        </template>
      </MEmpty>
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
import { getErrorStatus } from '@/types/errors'
import { isCanceledError } from '@/api/request'

const products = ref<Product[]>([])
const loading = ref(true)
/** 加载失败文案：与「暂无产品数据」区分 */
const loadError = ref('')
/** 当前错误是否值得重试：403 重试只会再吃一次 403 */
const loadErrorRetryable = ref(true)
const searchQuery = ref('')
const page = ref(1)
const totalItems = ref(0)
// 2026-10-18 OCR 评审：请求序号。搜索与翻页并发时，旧响应后到会覆盖新结果。
let loadSeq = 0

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
  const seq = ++loadSeq
  loading.value = true
  // 请求开始即清错误态，避免成功后仍显示上一次的失败文案
  loadError.value = ''
  try {
    // F-FE-MOBILE-07：服务端搜索；AUD-22：服务端分页（此前固定 page=1，
    // 第 201 条起永久不可达）
    const res = await productApi.list({ page: page.value, per_page: MOBILE_LIST_PAGE_SIZE, search: searchQuery.value })
    if (seq !== loadSeq) return // 2026-10-18 OCR 评审：丢弃过期响应
    products.value = res.items ?? []
    totalItems.value = res.total ?? 0
  } catch (e) {
    if (seq !== loadSeq) return
    // 切路由会 abort 在途 GET：这不是失败，不能把 toast 弹到新页面上
    if (isCanceledError(e)) return
    console.error('[MProductView] load failed:', e)
    // 2026-10-18 OCR 评审：失败时清空行——page/searchQuery 已是新值，旧行留着
    // 等于用旧数据冒充新条件的查询结果。保留 totalItems：分页器不消失，
    // 用户可退回上一页重试。
    products.value = []
    // 失败必须留下持久错误态，否则与「暂无产品数据」无法区分
    const status = getErrorStatus(e)
    loadErrorRetryable.value = status !== 403
    loadError.value = status === 403 ? '无查看权限，请联系管理员' : '产品加载失败，请检查网络后重试'
    // 403 已由全局拦截器提示，且页面已隐藏「重试」，不再弹「请重试」自相矛盾
    if (status !== 403) showToast('产品加载失败，请重试', 'error')
  } finally {
    // 过期请求的 finally 不能关掉新请求的 loading
    if (seq === loadSeq) loading.value = false
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
