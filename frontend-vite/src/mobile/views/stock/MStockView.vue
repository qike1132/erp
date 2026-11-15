<template>
  <div class="m-stock">
    <!-- Search Bar -->
    <div class="m-stock-search">
      <MSearchBar v-model="searchQuery" placeholder="搜索物料名称或编码…" @search="onSearch" />
    </div>

    <!-- Filter Tabs -->
    <MFilterChips
      v-model="selectedTab"
      :chips="tabOptions"
      class="m-stock-tabs"
    />

    <!-- Loading -->
    <MSkeleton v-if="loading" variant="list" :count="5" />

    <!-- Stock List -->
    <template v-else>
      <div v-if="filteredStock.length" class="m-stock-list">
        <MCard
          v-for="item in filteredStock"
          :key="item.product_id"
          clickable
          padded
          class="m-stock-card"
        >
          <div class="m-stock-main">
            <div class="m-stock-info">
              <span class="m-stock-name">{{ item.product_name }}</span>
              <span class="m-stock-code">{{ codeOf(item) || '—' }}</span>
            </div>
            <div class="m-stock-qty">
              <span :class="['m-stock-qty-val', getQtyClass(item)]">
                {{ formatQty(item.inventory_balance) }}
              </span>
              <span class="m-stock-qty-unit">个</span>
            </div>
          </div>
          <div v-if="isOutOfStock(item)" class="m-stock-meta">
            <MBadge variant="warning" dot>零库存</MBadge>
          </div>
        </MCard>
      </div>

      <MEmpty v-else-if="loadError" :title="loadError">
        <template v-if="loadErrorRetryable" #action>
          <button
            type="button"
            style="margin-top: 12px; padding: 8px 18px; border-radius: 8px; border: 1px solid var(--m-border, #dbe3ef); background: #fff; font: inherit;"
            @click="loadStock()"
          >重试</button>
        </template>
      </MEmpty>
      <MEmpty v-else :title="searchQuery ? '未找到匹配物料' : '暂无库存数据'" />

      <UiPagination
        v-if="totalItems > MOBILE_LIST_PAGE_SIZE"
        :current-page="page"
        :total-pages="Math.ceil(totalItems / MOBILE_LIST_PAGE_SIZE)"
        :total-items="totalItems"
        @update:current-page="(p: number) => { page = p; loadStock() }"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { stockApi } from '@/api'
import { MOBILE_LIST_PAGE_SIZE } from '@/mobile/constants'
import type { InventoryItem } from '@/types'
import MCard from '@/mobile/components/MCard.vue'
import MSearchBar from '@/mobile/components/MSearchBar.vue'
import MFilterChips from '@/mobile/components/MFilterChips.vue'
import MBadge from '@/mobile/components/MBadge.vue'
import MSkeleton from '@/mobile/components/MSkeleton.vue'
import MEmpty from '@/mobile/components/MEmpty.vue'
import { showToast } from '@/composables/useToast'
import { getErrorStatus } from '@/types/errors'
import { isCanceledError } from '@/api/request'

const stockItems = ref<InventoryItem[]>([])
const loading = ref(true)
/** 加载失败文案：与「暂无库存数据」区分，避免后端 500 被当成业务事实 */
const loadError = ref('')
/** 当前错误是否值得重试：403 重试只会再吃一次 403 */
const loadErrorRetryable = ref(true)
const searchQuery = ref('')
const selectedTab = ref('all')
const page = ref(1)
const totalItems = ref(0)
// 2026-10-18 OCR 评审：请求序号。切换 chip / 搜索 / 翻页都会发新请求，
// 若旧响应后到会无条件覆盖列表，出现「点的是零库存、展示的是全部」。
let loadSeq = 0

const tabOptions = [
  { value: 'all', label: '全部' },
  { value: 'active', label: '在库' },
  { value: 'zero', label: '零库存' },
]

// 2026-10-17 审计 AUD-22：库存状态筛选已下推服务端（stock_status），
// 本地不再对截断后的首页数据过滤——否则「零库存」只反映前 200 条。
const filteredStock = computed(() => stockItems.value)

function formatQty(val: number | null | undefined): string {
  if (val == null) return '0'
  return Number(val).toLocaleString('zh-CN')
}

/** 库存接口返回「库存（结余）」= inventory_balance；无 current_stock 字段。 */
function isOutOfStock(item: InventoryItem): boolean {
  return (item.inventory_balance ?? 0) <= 0
}

/** 编码取 product_barcode（接口无 barcode 字段）。 */
function codeOf(item: InventoryItem): string {
  return item.product_barcode || ''
}

function getQtyClass(item: InventoryItem): string {
  if (isOutOfStock(item)) return 'low'
  if ((item.inventory_balance ?? 0) > 1000) return 'high'
  return ''
}

async function loadStock() {
  const seq = ++loadSeq
  loading.value = true
  // 每次请求开始先清错误态：否则一次失败后，后续成功且结果为空时仍显示失败文案
  loadError.value = ''
  try {
    // F-FE-MOBILE-07：服务端筛选；AUD-22：库存状态同样下推服务端 + 服务端分页
    const res = await stockApi.inventory({
      page: page.value,
      per_page: MOBILE_LIST_PAGE_SIZE,
      product: searchQuery.value,
      stock_status: selectedTab.value === 'all' ? '' : selectedTab.value,
    })
    if (seq !== loadSeq) return // 2026-10-18 OCR 评审：丢弃过期响应
    stockItems.value = res.data ?? []
    totalItems.value = res.total_items ?? 0
  } catch (e) {
    if (seq !== loadSeq) return
    // 切路由会 abort 在途 GET：这不是失败，不能把 toast 弹到新页面上
    if (isCanceledError(e)) return
    console.error('[MStockView] load failed:', e)
    // 2026-10-18 OCR 评审：清空行但保留 totalItems——旧筛选/旧页的行不能顶着新
    // chip 展示，同时分页器不消失、用户可重试。
    stockItems.value = []
    // 失败必须留下持久错误态：只弹 3 秒 toast 时页面与「真的没数据」完全一致
    const status = getErrorStatus(e)
    loadErrorRetryable.value = status !== 403
    loadError.value = status === 403 ? '无查看权限，请联系管理员' : '库存加载失败，请检查网络后重试'
    showToast('库存加载失败，请重试', 'error')
  } finally {
    // 过期请求的 finally 不能关掉新请求的 loading
    if (seq === loadSeq) loading.value = false
  }
}

function onSearch() {
  page.value = 1
  loadStock()
}

watch(selectedTab, () => {
  page.value = 1
  loadStock()
})

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

</style>
