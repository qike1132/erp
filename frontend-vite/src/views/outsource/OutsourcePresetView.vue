<template>
  <div class="hu-container">
    <div class="page-card page-card-main">
      <!-- 卡片头部：Tab 导航与搜索框同一行（Tab 靠左，搜索靠右） -->
      <div class="page-card-header">
        <HubeiRouteTabs />

        <!-- 产品搜索：选中后为其配置工序 -->
        <div class="preset-search">
          <div class="preset-search-field">
            <UiAutocomplete
              v-model="searchText"
              :search-fn="searchProducts"
              placeholder="搜索产品名称/条码，选中后为其配置工序"
              append-to="self"
              suppress-after-select
              :search-delay-ms="500"
              :show-loading="false"
              @select="onPickProduct($event as ProductSuggestion)"
            >
              <template #option="{ item }">
                <div class="preset-ac-option">
                  <span class="preset-ac-name">{{ item.name }}</span>
                  <span v-if="item.barcode" class="preset-ac-barcode">{{ item.barcode }}</span>
                </div>
              </template>
            </UiAutocomplete>
          </div>
          <button class="preset-reset-btn" aria-label="重置" @click="searchText = ''">
            <FontAwesomeIcon icon="redo" aria-hidden="true" />
          </button>
        </div>
      </div>

      <!-- 内容区 -->
      <div class="page-card-body">
        <div class="hu-tab-content">
          <OutsourcePresetTab
            :pending-products="pendingProducts"
            @remove-pending="removePending"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * OutsourcePresetView.vue — 工序预设页面（/outsource/presets）
 *
 * 原 /beile-order 合并页中「工序预设」Tab 拆分为独立路由页面，
 * 管理 SKU 外发工序模板（OutsourcePresetTab）。
 * 产品搜索框置于卡片头部，与 Tab 导航同一行；搜索选中但尚无预设的
 * 产品由本页维护并下发给子组件（保证能直接为其配置工序）。
 */
import { ref } from 'vue'
import OutsourcePresetTab from '@/views/outsource/components/OutsourcePresetTab.vue'
import HubeiRouteTabs from '@/views/hubei/HubeiRouteTabs.vue'
import UiAutocomplete from '@/components/ui/UiAutocomplete.vue'
import { outsourceApi } from '@/api'
import type { HubeiProductSearchItem } from '@/api/outsource'

/** 已搜索选中但尚无预设的产品（保证能直接为其配置） */
const pendingProducts = ref<{ product_id: number; product_name: string; product_barcode: string | null; factory: string | null }[]>([])

function removePending(productId: number) {
  pendingProducts.value = pendingProducts.value.filter((x) => x.product_id !== productId)
}

// ===== 产品搜索 =====
const searchText = ref('')

type ProductSuggestion = HubeiProductSearchItem

async function searchProducts(q: string): Promise<ProductSuggestion[]> {
  if (!q.trim()) return []
  try {
    // 仅返回工厂=湖北 的 SKU（后端已过滤），与 /product 的工厂标记联动
    return (await outsourceApi.productSearch(q)).slice(0, 8)
  } catch {
    return []
  }
}

function onPickProduct(p: ProductSuggestion) {
  if (!pendingProducts.value.some((x) => x.product_id === p.id)) {
    pendingProducts.value = [
      ...pendingProducts.value,
      { product_id: p.id, product_name: p.name, product_barcode: p.barcode || null, factory: p.factory || '湖北' },
    ]
  }
  searchText.value = ''
}
</script>

<style scoped lang="scss">
@use '@/styles/hubei-page.scss' as *;

/* Tab 导航与搜索框同一行：Tab 靠左，搜索靠右，避免搜索框被挤压 */
.page-card-header {
  flex-wrap: nowrap;
  gap: 12px;
}
.page-card-header :deep(.hu-tabs-bar) {
  padding: 0;
  flex-shrink: 0;
}
.preset-search {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
  flex-shrink: 0;
}
.preset-search-field {
  width: 360px;
  max-width: 100%;
}
.preset-reset-btn {
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
.preset-reset-btn:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-600);
  transform: translateY(-1px);
}
.preset-ac-option {
  display: flex;
  flex-direction: column;
  gap: 2px;
  align-items: flex-start;
}
.preset-ac-name { color: var(--color-text); font-weight: 500; font-size: 13px; }
.preset-ac-barcode { color: var(--color-text-muted); font-size: 12px; font-family: ui-monospace, Menlo, Consolas, monospace; }
</style>
