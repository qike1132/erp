<template>
  <div class="pd-col-title">
    <span><FontAwesomeIcon icon="list" aria-hidden="true" /> 产品列表</span>
    <div class="pd-col-actions">
      <UiSelect
        v-model="customerFilter"
        label="客户筛选"
        placeholder="客户"
        style="width: 150px; flex-shrink: 0"
        :options="customerFilterOptions"
      />
      <!-- 必须走 setSearchTerm，不能写 `searchTerm = $event`：search 是 useEnhancedList
           暴露的 readonly ref，直接赋值被 Vue 静默忽略（仅 dev 警告），关键词永远进不了查询。 -->
      <UiSearchInput :model-value="searchTerm" placeholder="搜索产品名称或69码..." @search="onSearchInput" @update:model-value="setSearchTerm" />
    </div>
  </div>
  <div class="pd-col-scroll">
    <div class="pd-table-wrap">
      <UiDataTable
        :data="paginatedProducts"
        :columns="productColumns"
        :loading="isLoading"
        paginator
        :rows="perPage"
        :total-records="total"
        row-key="id"
        @page="onPageChange"
      >
        <template #empty>
          <div class="pd-empty">
            <FontAwesomeIcon icon="inbox" class="pd-empty-icon" aria-hidden="true" />
            <p class="pd-empty-text">{{ searchTerm ? '未找到匹配的产品' : '暂无产品，请先添加' }}</p>
          </div>
        </template>
        <template #column-body-image="{ row }">
          <div v-if="(row as Product).image && !failedImageIds.has((row as Product).id)" class="pd-thumb-box" @click="emit('open-image', (row as Product).image_original ?? (row as Product).image!)" @error.capture="handleImageError($event, row as Product)">
            <img loading="lazy" :src="thumbSrc(row as Product)" class="pd-thumb-img" :alt="(row as Product).name" />
          </div>
          <div v-else class="pd-thumb-box">
            <div class="pd-no-image"><FontAwesomeIcon icon="image" aria-hidden="true" /></div>
          </div>
        </template>
        <template #column-body-name="{ row }"><span class="pd-name">{{ (row as Product).name }}</span></template>
        <template #column-body-barcode="{ row }"><span class="pd-barcode">{{ (row as Product).barcode || '-' }}</span></template>
        <template #column-body-price="{ row }"><span class="pd-price">{{ formatCurrency((row as Product).price) }}</span></template>
        <template #column-body-factory="{ row }"><span class="pd-factory">{{ (row as Product).factory || '-' }}</span></template>
        <template #column-body-customers="{ row }">
          <div class="pd-customers">
            <span v-for="c in (row as Product).customers ?? []" :key="c.id" class="pd-customer-tag">{{ c.name }}</span>
            <span v-if="!((row as Product).customers ?? []).length" class="pd-customer-none" title="未挂客户 = 所有客户都能选到这个 SKU">未分配</span>
          </div>
        </template>
        <template #column-body-actions="{ row }">
          <div class="pd-actions">
            <button class="pd-act-btn pd-act-bom" title="配置BOM表" aria-label="设置" @click="emit('open-bom', row as Product)">
              <FontAwesomeIcon icon="cogs" aria-hidden="true" />
            </button>
            <button class="pd-act-btn pd-act-edit" title="编辑" aria-label="编辑" @click="emit('open-edit', row as Product)">
              <FontAwesomeIcon icon="edit" aria-hidden="true" />
            </button>
            <button class="pd-act-btn pd-act-delete" title="删除" :disabled="actionId === (row as Product).id" aria-label="删除" @click="emit('delete', row as Product)">
              <FontAwesomeIcon icon="trash" aria-hidden="true" />
            </button>
          </div>
        </template>
      </UiDataTable>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import { useEnhancedList } from '@/composables/useEnhancedList'
import { useCatalogStore } from '@/stores/catalog'
import { formatCurrency } from '@/utils/format'
import { resolveStaticUrl } from '@/api/request'
import type { ProductCustomerRef } from '@/types'

interface Product {
  id: number
  name: string
  barcode: string
  price: number
  image: string | null
  image_thumb?: string | null
  image_original?: string | null
  factory?: string
  current_stock?: number
  customers?: ProductCustomerRef[]
}

defineProps<{
  actionId: number | null
}>()

const emit = defineEmits<{
  'open-bom': [product: Product]
  'open-edit': [product: Product]
  'delete': [product: Product]
  'open-image': [src: string]
}>()

// 客户筛选：'all' | 'unassigned' | 'id:<客户ID>'。
// 「未分配」是补齐存量归属的入口 —— 未挂客户的 SKU 对所有客户可见，不急，但要能找得到。
const customerFilter = ref('all')
const catalogStore = useCatalogStore()
catalogStore.ensureActiveCustomerNames().catch(() => { /* 失败保持空列表，下次重试 */ })
const customerFilterOptions = computed(() => [
  { label: '全部客户', value: 'all' },
  { label: '未分配', value: 'unassigned' },
  ...catalogStore.activeCustomerNames.map((c) => ({ label: c.name, value: `id:${c.id}` })),
])

// 产品列表
const {
  items: paginatedProducts, total, search: searchTerm,
  isLoading,
  perPage, handlePageChange: goToPage, handleSizeChange, handleSearch: setSearchTerm,
} = useEnhancedList<Product>({
  key: 'products-list',
  url: '/products/list',
  perPage: 20,
  staleTime: 30_000,
  extraParams: () => {
    if (customerFilter.value === 'unassigned') return { only_unassigned: true }
    if (customerFilter.value.startsWith('id:')) {
      return { customer_id: Number(customerFilter.value.slice(3)) }
    }
    return {}
  },
})

function onSearchInput(q: string) {
  setSearchTerm(q)
}

/** UiDataTable 列定义 */
const productColumns: TableColumn[] = [
  { field: 'image', header: '产品图片', align: 'center', width: '120px' },
  { field: 'name', header: '产品名称', align: 'left' },
  { field: 'barcode', header: '69码', align: 'center', width: '110px' },
  { field: 'price', header: '产品价格', align: 'center', width: '96px' },
  { field: 'factory', header: '工厂', align: 'center', width: '80px' },
  { field: 'customers', header: '客户', align: 'left', width: '140px' },
  { field: 'actions', header: '操作', align: 'center', width: '132px' },
]

/** UiDataTable 分页变化处理（PrimeVue page 为 0 索引） */
function onPageChange(event: { page: number; rows: number }) {
  goToPage(event.page + 1)
  if (event.rows !== perPage.value) handleSizeChange(event.rows)
}

// ===== 图片加载失败处理 =====
const failedImageIds = ref<Set<number>>(new Set())
// 缩略图缺失/404 时先回退原图（存量老图可能还没补缩略图），原图也失败才显示占位
const thumbFallbackIds = ref<Set<number>>(new Set())

/** 列表用图：优先 400px 缩略图（后端出站派生 image_thumb），拿不到则回退原图 */
function thumbSrc(row: Product): string {
  const thumb = row.image_thumb
  if (thumb && !thumbFallbackIds.value.has(row.id)) return resolveStaticUrl(thumb)
  return resolveStaticUrl(row.image ?? '')
}

function handleImageError(event: Event, row: Product) {
  const target = event.target as HTMLImageElement | null
  const original = resolveStaticUrl(row.image ?? '')
  // 缩略图失败 → 直接切到原图。不能只改 ref 等下一次渲染：
  // 刷新时 404 可能来自缓存，error 会在 Vue 完成 patch 前触发，单靠状态更新会漏掉回退。
  if (row.image_thumb && !thumbFallbackIds.value.has(row.id) && original) {
    thumbFallbackIds.value = new Set(thumbFallbackIds.value).add(row.id)
    if (target) target.src = original
    return
  }
  failedImageIds.value = new Set(failedImageIds.value).add(row.id)
}
</script>

<style scoped>
.pd-col-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 0 20px;
  height: 52px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  flex-shrink: 0;
}
.pd-col-title i {
  font-size: 14px;
  color: var(--color-primary-500);
}
.pd-col-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}
/* 客户筛选与 UiSearchInput 并排等高：两控件统一 40px 高/13.5px 字/10px 圆角。
   筛选框侧收 UiSelect 基础样式(44px/15px)；搜索框侧收其默认 py-2.5(44px)/text-sm(14px)。 */
.pd-col-actions :deep(.ui-select-input) {
  min-width: 0;
  min-height: 40px;
  height: 40px;
  padding: 0 2.5rem 0 0.75rem;
  font-size: 13.5px;
  line-height: 1;
  border-radius: 10px;
}
.pd-col-actions :deep(.ui-search-input input) {
  height: 40px;
  min-height: 40px;
  padding-top: 0;
  padding-bottom: 0;
  font-size: 13.5px;
  line-height: 1;
  border-radius: 10px;
}
/* 搜索框(max-w-sm=384px)在窄容器下会把 150px 的筛选框 flex 压缩(实测压到 107px)，
   减去左右 padding 后内容区仅 ~51px，「全部客户」被裁 —— 禁止收缩(内联 flex-shrink:0)。 */
.pd-col-actions :deep(.ui-select-input) {
  min-width: 0;
}
.pd-col-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 0;
}

/* ===== 表格 ===== */
.pd-table-wrap {
  overflow: hidden;
  border: 1px solid var(--color-border-light, #e2e8f0);
}
.pd-factory { font-size: 13px; font-weight: 500; color: var(--color-text); }

/* ===== 客户列 ===== */
.pd-customers { display: flex; flex-wrap: wrap; gap: 4px; }
.pd-customer-tag {
  display: inline-block;
  padding: 1px 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-primary-600);
  background: var(--color-primary-50);
  border: 1px solid var(--color-primary-100);
  border-radius: 999px;
  white-space: nowrap;
}
.pd-customer-none {
  font-size: 12px;
  color: var(--color-text-secondary);
  background: var(--color-surface, #f8fafc);
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 999px;
  padding: 1px 8px;
  white-space: nowrap;
}
.pd-thumb-box {
  width: 120px;
  height: 120px;
  border-radius: 10px;
  overflow: hidden;
  cursor: pointer;
  transition: transform 0.3s ease, box-shadow 0.3s ease;
  background: var(--color-surface, #f8fafc);
  border: none;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
.pd-thumb-box:hover { transform: scale(1.05); box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
.pd-thumb-img { width: 100%; height: 100%; object-fit: contain; }
.pd-no-image {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-surface, #f8fafc);
  color: var(--color-text-secondary);
  font-size: 36px;
  opacity: 0.5;
}
.pd-name { font-size: 14px; font-weight: 500; color: var(--color-text); line-height: 1.5; }
.pd-barcode { font-size: 12px; color: var(--color-text-secondary); font-family: Consolas, Monaco, monospace; letter-spacing: 0.02em; }
.pd-price { font-size: 13px; font-weight: 600; color: var(--color-danger-500); }

/* ===== 操作按钮 ===== */
.pd-actions { display: flex; gap: 4px; justify-content: center; }
.pd-act-btn {
  width: 36px;
  height: 36px;
  border-radius: 9px;
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  transition: background 0.2s ease, transform 0.2s ease;
  cursor: pointer;
}
.pd-act-bom { background: var(--color-primary-50); color: var(--color-primary-600); }
.pd-act-bom:hover { background: var(--color-primary-100); transform: translateY(-1px); }
.pd-act-edit { background: var(--color-warning-50); color: var(--color-warning-600); }
.pd-act-edit:hover { background: var(--color-warning-100); transform: translateY(-1px); }
.pd-act-delete { background: var(--color-danger-50); color: var(--color-danger-500); }
.pd-act-delete:hover { background: var(--color-danger-100); transform: translateY(-1px); }

/* ===== 空状态 & 加载 ===== */
.pd-empty { padding: 40px 20px; text-align: center; display: flex; flex-direction: column; align-items: center; gap: 10px; }
.pd-empty-icon { font-size: 28px; color: var(--color-text-secondary); opacity: 0.5; }
.pd-empty-text { font-size: 14px; color: var(--color-text-secondary); margin: 0; }
</style>
