<template>
  <div class="pd-col-title">
    <span><FontAwesomeIcon icon="list" aria-hidden="true" /> 产品列表</span>
    <div class="pd-col-actions">
      <UiSearchInput :model-value="searchTerm" placeholder="搜索产品名称或69码..." @search="onSearchInput" @update:model-value="searchTerm = $event" />
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
          <div v-if="(row as Product).image && !failedImageIds.has((row as Product).id)" class="pd-thumb-box" @click="emit('open-image', (row as Product).image!)">
            <img loading="lazy" :src="resolveStaticUrl((row as Product).image!)" class="pd-thumb-img" :alt="(row as Product).name" @error="handleImageError(row as Product)" />
          </div>
          <div v-else class="pd-thumb-box">
            <div class="pd-no-image"><FontAwesomeIcon icon="image" aria-hidden="true" /></div>
          </div>
        </template>
        <template #column-body-name="{ row }"><span class="pd-name">{{ (row as Product).name }}</span></template>
        <template #column-body-barcode="{ row }"><span class="pd-barcode">{{ (row as Product).barcode || '-' }}</span></template>
        <template #column-body-price="{ row }"><span class="pd-price">{{ formatCurrency((row as Product).price) }}</span></template>
        <template #column-body-factory="{ row }"><span class="pd-factory">{{ (row as Product).factory || '-' }}</span></template>
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
import { ref } from 'vue'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
import { useEnhancedList } from '@/composables/useEnhancedList'
import { formatCurrency } from '@/utils/format'
import { resolveStaticUrl } from '@/api/request'

interface Product {
  id: number
  name: string
  barcode: string
  price: number
  image: string | null
  factory?: string
  current_stock?: number
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
})

function onSearchInput(q: string) {
  setSearchTerm(q)
}

/** UiDataTable 列定义 */
const productColumns: TableColumn[] = [
  { field: 'image', header: '产品图片', align: 'center' },
  { field: 'name', header: '产品名称', align: 'left' },
  { field: 'barcode', header: '69码', align: 'center' },
  { field: 'price', header: '产品价格', align: 'center' },
  { field: 'factory', header: '工厂', align: 'center' },
  { field: 'actions', header: '操作', align: 'center' },
]

/** UiDataTable 分页变化处理（PrimeVue page 为 0 索引） */
function onPageChange(event: { page: number; rows: number }) {
  goToPage(event.page + 1)
  if (event.rows !== perPage.value) handleSizeChange(event.rows)
}

// ===== 图片加载失败处理 =====
const failedImageIds = ref<Set<number>>(new Set())

function handleImageError(row: Product) {
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
.pd-col-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}

/* ===== 表格 ===== */
.pd-table-wrap {
  overflow: hidden;
  border: 1px solid var(--color-border-light, #e2e8f0);
}
.pd-factory { font-size: 13px; font-weight: 500; color: var(--color-text); }
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
