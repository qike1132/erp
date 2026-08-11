<template>
  <div class="bo-container">
    <div class="page-card page-card-main">
      <!-- 卡片头部 -->
      <div class="page-card-header">
        <div class="bo-header-left">
          <HeaderTabs />
        </div>
        <div v-if="tabRef" class="bo-filter-bar">
          <div class="bo-search-field">
            <UiAutocomplete
              ref="productAc"
              v-model="tabRef.filters.orderNo"
              :searchFn="searchProducts"
              placeholder="输入关键字，下拉选择产品"
              appendTo="self"
              suppress-after-select
              :search-delay-ms="500"
              :show-loading="false"
              @select="tabRef.applyProductFilter(($event as ProductSuggestion).name)"
            >
              <template #option="{ item }">
                <div class="bo-ac-option">
                  <span class="bo-ac-name">{{ item.name }}</span>
                  <span v-if="item.barcode" class="bo-ac-barcode">{{ item.barcode }}</span>
                </div>
              </template>
            </UiAutocomplete>
          </div>
          <div class="bo-search-field">
            <UiAutocomplete
              ref="customerAc"
              v-model="tabRef.filters.customer"
              :searchFn="searchCustomers"
              placeholder="输入关键字，下拉选择客户"
              appendTo="self"
              suppress-after-select
              :search-delay-ms="500"
              :show-loading="false"
              @select="tabRef.applyCustomerFilter(($event as CustomerSuggestion).name)"
            />
          </div>
          <div class="bo-filter-actions">
            <button class="bo-action-btn bo-action-primary" @click="handleSearchClick()">
              <FontAwesomeIcon icon="search" style="margin-right: 4px" aria-hidden="true" />查询
            </button>
            <button class="bo-action-btn" @click="tabRef.handleReset()" aria-label="重置">
              <FontAwesomeIcon icon="redo" aria-hidden="true" />
            </button>
          </div>
        </div>
      </div>

      <!-- 内容区 -->
      <div class="page-card-body">
        <BeileOrderTab ref="tabRef" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * BeileOrderView.vue — 湖北订单页面
 *
 * 职责：作为湖北订单的容器组件，承载 BeileOrderTab 子组件。
 * 筛选 UI 放在 .page-card-header 右侧，与 HeaderTabs 同一行；
 * Tab 通过 ref 暴露 reactive filters + handleSearch/Reset 共享状态。
 * 页面锁定 factory=湖北，供管理员与湖北用户查看本厂订单。
 */
import { ref } from 'vue'
import BeileOrderTab from './BeileOrderTab.vue'
import HeaderTabs from '@/layouts/components/HeaderTabs.vue'
import UiAutocomplete from '@/components/ui/UiAutocomplete.vue'
import { productApi, customerApi } from '@/api'
// FontAwesomeIcon 已在 main.ts 全局注册

const tabRef = ref<InstanceType<typeof BeileOrderTab> | null>(null)
/** UiAutocomplete 为泛型组件，InstanceType 无法推导，用结构化类型描述暴露的句柄 */
type AutocompleteHandle = { setSuppressed: (v: boolean) => void }
const productAc = ref<AutocompleteHandle | null>(null)
const customerAc = ref<AutocompleteHandle | null>(null)

/**
 * 点击查询：确认筛选后抑制两个下拉面板再次展开，
 * 避免编辑已提交的搜索词时面板遮挡表格造成闪烁。
 * 清空输入框或点重置后自动恢复下拉功能。
 */
function handleSearchClick() {
  tabRef.value?.handleSearch()
  if (tabRef.value?.filters.orderNo.trim()) {
    productAc.value?.setSuppressed?.(true)
  }
  if (tabRef.value?.filters.customer.trim()) {
    customerAc.value?.setSuppressed?.(true)
  }
}

// ===== 产品自动补全 =====
type ProductSuggestion = { id: number; name: string; barcode?: string }

async function searchProducts(q: string): Promise<ProductSuggestion[]> {
  if (!q.trim()) return []
  try {
    const res = await productApi.search(q)
    const list = Array.isArray(res) ? res : ((res as unknown as { items?: unknown[] }).items ?? [])
    return (list as Array<Record<string, unknown>>).slice(0, 8).map((p) => ({
      id: Number(p.id),
      name: String(p.name ?? ''),
      barcode: p.barcode ? String(p.barcode) : undefined,
    }))
  } catch {
    return []
  }
}

// ===== 客户自动补全 =====
type CustomerSuggestion = { id: number; name: string }

let cachedCustomerNames: CustomerSuggestion[] | null = null

async function searchCustomers(q: string): Promise<CustomerSuggestion[]> {
  try {
    if (!cachedCustomerNames) {
      const names = await customerApi.activeNames()
      cachedCustomerNames = (Array.isArray(names) ? names : []).map((c: unknown) => {
        const entry = c as Record<string, unknown>
        return { id: Number(entry.id), name: String(entry.name ?? '') }
      })
    }
    const kw = q.trim().toLowerCase()
    if (!kw) return cachedCustomerNames.slice(0, 8)
    return cachedCustomerNames.filter((c) => c.name.toLowerCase().includes(kw)).slice(0, 8)
  } catch {
    return []
  }
}
</script>

<style scoped>
/* Container */
.bo-container {
  padding: 0;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  contain: layout style;
  overflow-anchor: none;
  overflow: hidden;
}


/* Card Header — 对齐 StockView / CaseView 布局 */
/* 卡片样式已迁移到全局 .page-card 系列（src/styles/app.css） */
.page-card-header :deep(.ht-bar) {
  width: auto;
  margin: 0;
}
.bo-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

/* 筛选区：搬至 header 右侧，与 HeaderTabs 同行 */
.bo-filter-bar {
  display: flex;
  gap: 12px;
  align-items: flex-end;
  padding: 0;
  border-bottom: none;
  flex-shrink: 0;
}
/* 自动补全输入容器 */
.bo-search-field {
  width: 220px;
}
/* 自动补全下拉选项样式（与原有风格一致） */
.bo-ac-option {
  display: flex;
  flex-direction: column;
  gap: 2px;
  align-items: flex-start;
}
.bo-ac-name {
  color: var(--color-text);
  font-weight: 500;
  font-size: 13px;
}
.bo-ac-barcode {
  color: var(--color-text-muted);
  font-size: 12px;
  font-family: ui-monospace, Menlo, Consolas, monospace;
}
.bo-filter-actions {
  display: flex;
  gap: 8px;
  align-items: flex-end;
}
.bo-action-btn {
  padding: 7px 14px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  background: white;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.3s ease, border-color 0.3s ease, transform 0.3s ease;
  color: var(--color-text-secondary);
  display: inline-flex;
  align-items: center;
  font-family: inherit;
  line-height: inherit;
}
.bo-action-primary { color: var(--color-primary-600); }
.bo-action-primary:hover {
  background: var(--color-primary-50);
  border-color: var(--color-primary-300);
  transform: translateY(-1px);
}
.bo-action-btn:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-600);
  transform: translateY(-1px);
}

/* 卡片主体样式复用全局 .page-card-body（src/styles/app.css） */

/* 表格区域上/左/右完全贴合卡片边缘（卡片自身有边框），分页栏贴底；
   内容区自身不再滚动（表格内部滚动），无需预留滚动条位 */
.bo-container .page-card-body {
  padding: 0;
  scrollbar-gutter: auto;
}

/* 窄屏：恢复 flex-wrap 让筛选区可换行，避免挤压 header */
@media (max-width: 900px) {
  .page-card-header {
    flex-wrap: wrap;
    gap: 8px;
  }
  .bo-filter-bar {
    flex-wrap: wrap;
    width: 100%;
  }
  .bo-search-field { width: 160px; }
}
</style>
