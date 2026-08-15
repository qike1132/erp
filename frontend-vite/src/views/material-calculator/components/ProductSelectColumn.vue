<template>
  <div class="mc-col mc-col-products">
    <div class="mc-col-title">
      <FontAwesomeIcon icon="boxes-stacked" aria-hidden="true" />
      产品选择
    </div>

    <!-- Search -->
    <div class="mc-search-wrapper">
      <div class="mc-search-input-group">
        <FontAwesomeIcon icon="search" class="mc-search-icon" aria-hidden="true" />
        <input
          v-model="searchQuery"
          type="text"
          placeholder="搜索产品名称或69码..."
          class="mc-search-input"
          @input="onSearchInput"
          @focus="onMcSearchFocus"
          @blur="hideMcSuggestions"
        />
        <button
          v-if="searchQuery"
          class="mc-search-clear"
          @click="
            searchQuery = '';
            onSearchInput()
          "
       aria-label="关闭">
          <FontAwesomeIcon icon="times" aria-hidden="true" />
        </button>
      </div>
      <div v-if="searchSuggestions.length" class="mc-search-dropdown">
        <div v-for="p in searchSuggestions" :key="p.id" class="mc-dropdown-item" @mousedown.prevent="onSelectFromSearch(p)">
          <div class="mc-dropdown-item-info">
            <span class="mc-dropdown-item-name">{{ p.name }}</span>
            <span v-if="p.barcode" class="mc-dropdown-item-meta">{{ p.barcode }}</span>
          </div>
          <span :class="['mc-bom-tag-mini', p.has_bom ? 'has-bom' : 'no-bom']">
            {{ p.has_bom ? '有BOM' : '无BOM' }}
          </span>
        </div>
      </div>
    </div>

    <!-- Filter bar -->
    <div class="mc-filter-bar">
      <button
        v-for="f in filterOptions"
        :key="f.value"
        :class="['mc-filter-btn', bomFilter === f.value ? 'active' : '']"
        @click="bomFilter = f.value"
      >
        {{ f.label }}
      </button>
    </div>

    <!-- S5: 产品数达上限提示 -->
    <div v-if="productCapHint && !loadingProducts" class="mc-cap-hint">{{ productCapHint }}</div>

    <!-- Product list -->
    <div ref="productListRef" class="mc-product-list">
      <div v-if="loadingProducts" class="mc-loading-state">
        <UiSpinner />
      </div>
      <div v-else-if="filteredProducts.length === 0" class="mc-empty-state">
        <FontAwesomeIcon icon="inbox" aria-hidden="true" />
        <span>暂无产品</span>
      </div>
      <template v-else>
        <VirtualList
          :items="filteredProducts"
          :itemHeight="80"
          :containerHeight="productListHeight"
          :itemKey="(p) => p.id"
        >
          <template #default="{ item: p }">
            <div
              :class="[
                'mc-product-item',
                selectedProductIds.includes(p.id) ? 'selected' : '',
                !p.has_bom ? 'disabled' : '',
              ]"
              @click="p.has_bom && emit('toggle-product', p)"
            >
              <FontAwesomeIcon :icon="selectedProductIds.includes(p.id) ? 'check-square' : 'square'" class="mc-checkbox" aria-hidden="true" />
              <div class="mc-product-details">
                <div class="mc-product-name">
                  {{ p.name }}
                </div>
                <div v-if="p.barcode" class="mc-product-code">
                  {{ p.barcode }}
                </div>
              </div>
              <span :class="['mc-bom-badge', p.has_bom ? 'has-bom' : 'no-bom']">
                {{ p.has_bom ? '有BOM' : '无BOM' }}
              </span>
            </div>
          </template>
        </VirtualList>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
// 产品选择列（含虚拟列表与搜索建议，从 MaterialCalculatorView.vue 抽出，模板原样搬移）
import type { MaterialCalcProduct } from '@/api'
import VirtualList from '@/components/ui/VirtualList.vue'
import { useMaterialCalc } from '../composables/useMaterialCalc'

defineProps<{
  selectedProductIds: number[]
}>()

const emit = defineEmits<{
  'toggle-product': [p: MaterialCalcProduct]
  'add-product': [p: MaterialCalcProduct, onSettled: (added: boolean) => void]
}>()

// 产品查询 / 搜索建议 / BOM 过滤 / 虚拟列表高度（逻辑抽至 composables/useMaterialCalc.ts）
const {
  searchQuery, searchSuggestions, bomFilter, loadingProducts, productCapHint,
  filteredProducts, productListRef, productListHeight,
  onSearchInput, onMcSearchFocus, hideMcSuggestions,
} = useMaterialCalc()

// 分类列表与筛选选项
const filterOptions: Array<{ label: string; value: 'all' | 'true' | 'false' }> = [
  { label: '全部', value: 'all' },
  { label: '有BOM', value: 'true' },
  { label: '无BOM', value: 'false' },
]

/** 搜索下拉选择产品：由父级执行 addProduct 并触发重算，添加成功时清空搜索状态（与原行为一致） */
function onSelectFromSearch(p: MaterialCalcProduct) {
  emit('add-product', p, (added) => {
    if (added) {
      searchSuggestions.value = []
      searchQuery.value = ''
    }
  })
}
</script>

<style scoped>
/* === Search === */
.mc-search-wrapper {
  position: relative;
  padding: 12px 16px;
}

.mc-search-input-group {
  position: relative;
  display: flex;
  align-items: center;
}

.mc-search-icon {
  position: absolute;
  left: 14px;
  color: var(--color-text-muted, #94a3b8);
  font-size: 14px;
  z-index: 2;
}

.mc-search-input {
  width: 100%;
  padding: 12px 40px 12px 42px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 11px;
  font-size: 14px;
  outline: none;
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
  background: white;
}

.mc-search-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }

.mc-search-input:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}

.mc-search-clear {
  position: absolute;
  right: 10px;
  background: none;
  border: none;
  color: var(--color-text-muted, #94a3b8);
  cursor: pointer;
  padding: 6px;
  border-radius: 50%;
  transition: background 0.2s ease, color 0.2s ease;
}

.mc-search-clear:hover {
  background: var(--color-surface, #f1f5f9);
  color: var(--color-text-secondary);
}

.mc-search-dropdown {
  position: absolute;
  top: calc(100% + 6px);
  left: 16px;
  right: 16px;
  background: white;
  border: 2px solid var(--color-primary-200);
  border-radius: 12px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.12);
  z-index: 1000;
  max-height: 320px;
  overflow-y: auto;
}

.mc-dropdown-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  cursor: pointer;
  transition: background 0.2s ease;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
}

.mc-dropdown-item:last-child {
  border-bottom: none;
}

.mc-dropdown-item:hover {
  background: var(--color-primary-50);
}

.mc-dropdown-item-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.mc-dropdown-item-name {
  font-weight: 600;
  font-size: 14px;
  color: var(--color-text);
}

.mc-dropdown-item-meta {
  font-size: 12px;
  color: var(--color-text-secondary);
}

/* === BOM Tags === */
.mc-bom-tag-mini {
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
}

.mc-bom-tag-mini.has-bom {
  background: var(--color-success-100);
  color: var(--color-success-700);
}

.mc-bom-tag-mini.no-bom {
  background: var(--color-danger-100);
  color: var(--color-danger-800);
}

.mc-bom-badge {
  padding: 5px 10px;
  border-radius: 7px;
  font-size: 11px;
  font-weight: 700;
  flex-shrink: 0;
}

.mc-bom-badge.has-bom {
  background: var(--color-success-100);
  color: var(--color-success-700);
}

.mc-bom-badge.no-bom {
  background: var(--color-danger-100);
  color: var(--color-danger-800);
}

/* === Filter Bar === */
.mc-filter-bar {
  display: flex;
  gap: 8px;
  padding: 0 16px 12px;
}

.mc-filter-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 9px 14px;
  background: white;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: border-color 0.2s ease, background 0.2s ease, transform 0.2s ease;
}

.mc-filter-btn:hover {
  background: white;
  border-color: var(--color-border, #cbd5e1);
  transform: translateY(-1px);
}

.mc-filter-btn.active {
  background: var(--color-primary-50);
  border-color: var(--color-primary-400);
  color: var(--color-primary-700);
}

/* === Product List === */
.mc-product-list {
  padding: 0 16px 16px;
  flex: 1;
  overflow: hidden;
  min-height: 0;
}

.mc-product-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 16px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 12px;
  margin: 4px 0;
  cursor: pointer;
  transition: border-color 0.3s ease, background 0.3s ease, transform 0.3s ease, box-shadow 0.3s ease;
  background: white;
  height: calc(100% - 8px);
  box-sizing: border-box;
}

.mc-product-item:hover {
  border-color: var(--color-primary-300);
  background: var(--color-primary-50);
  transform: translateX(4px);
  box-shadow: 0 2px 12px rgba(0, 148, 191, 0.1);
}

.mc-product-item.selected {
  border-color: var(--color-primary-500);
  background: var(--color-primary-50);
  box-shadow: 0 3px 16px rgba(0, 148, 191, 0.15);
}

/* S4: 无 BOM 产品禁用交互 */
.mc-product-item.disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.mc-product-item.disabled:hover {
  border-color: var(--color-border-light, #e2e8f0);
  background: white;
  transform: none;
  box-shadow: none;
}

/* S5: 产品数达上限提示 */
.mc-cap-hint {
  padding: 6px 12px;
  margin: 0 16px 6px;
  font-size: 12px;
  color: var(--color-text-secondary);
  background: var(--color-warning-50);
  border-radius: 8px;
  text-align: center;
  flex-shrink: 0;
}

.mc-checkbox {
  font-size: 18px;
  cursor: pointer;
  flex-shrink: 0;
  color: var(--color-border, #cbd5e1);
  transition: color 0.2s;
}

.selected .mc-checkbox {
  color: var(--color-primary-500);
}

.mc-product-details {
  flex: 1;
  min-width: 0;
}

.mc-product-name {
  font-weight: 650;
  font-size: 14px;
  color: var(--color-text);
  margin-bottom: 3px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.mc-product-code {
  font-size: 12px;
  color: var(--color-text-secondary);
}

/* === Empty & Loading States === */
.mc-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-text-muted, #94a3b8);
  font-size: 14px;
}

.mc-empty-state i {
  font-size: 28px;
  opacity: 0.5;
}

.mc-loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-primary-500);
  font-size: 14px;
}

.mc-loading-state i {
  font-size: 20px;
}
</style>
