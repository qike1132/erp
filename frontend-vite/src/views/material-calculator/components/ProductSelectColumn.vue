<template>
  <div class="mc-col mc-col-products">
    <div class="mc-col-title">
      <FontAwesomeIcon icon="boxes-stacked" aria-hidden="true" />
      产品选择
      <span class="mc-col-tail">{{ filteredProducts.length }} 条</span>
    </div>

    <!-- 搜索与 BOM 过滤合并为一行：原先各占一整行，前置控件共吃掉 153px -->
    <div class="mc-col-tools">
      <ProductSearchPanel
        v-model="searchQuery"
        :suggestions="searchSuggestions"
        @search-input="onSearchInput"
        @search-focus="onMcSearchFocus"
        @search-blur="hideMcSuggestions"
        @select="onSelectFromSearch"
      />

      <ProductFilterBar v-model="bomFilter" :options="filterOptions" />
    </div>

    <div v-if="productCapHint && !loadingProducts" class="mc-cap-hint">{{ productCapHint }}</div>

    <ProductList
      :products="filteredProducts"
      :loading="loadingProducts"
      :selected-ids="selectedProductIds"
      @toggle="emit('toggle-product', $event)"
    />
  </div>
</template>

<script setup lang="ts">
import type { MaterialCalcProduct } from '@/api'
import ProductSearchPanel from './ProductSearchPanel.vue'
import ProductFilterBar from './ProductFilterBar.vue'
import ProductList from './ProductList.vue'
import { useProductPicker } from '../composables/useProductPicker'

defineProps<{
  selectedProductIds: number[]
}>()

const emit = defineEmits<{
  'toggle-product': [p: MaterialCalcProduct]
  'add-product': [p: MaterialCalcProduct, onSettled: (added: boolean) => void]
}>()

const {
  searchQuery, searchSuggestions, bomFilter, loadingProducts, productCapHint,
  filteredProducts,
  onSearchInput, onMcSearchFocus, hideMcSuggestions,
} = useProductPicker()

const filterOptions: Array<{ label: string; value: 'all' | 'true' | 'false' }> = [
  { label: '全部', value: 'all' },
  { label: '有BOM', value: 'true' },
  { label: '无BOM', value: 'false' },
]

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
.mc-cap-hint {
  padding: 6px 10px;
  margin: 0 12px 6px;
  font-size: 12px;
  color: var(--color-warning-800);
  background: var(--color-warning-50);
  border-radius: 6px;
  text-align: center;
  flex-shrink: 0;
}
</style>
