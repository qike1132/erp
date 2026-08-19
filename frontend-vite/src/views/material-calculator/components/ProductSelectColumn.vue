<template>
  <div class="mc-col mc-col-products">
    <div class="mc-col-title">
      <FontAwesomeIcon icon="boxes-stacked" aria-hidden="true" />
      产品选择
    </div>

    <ProductSearchPanel
      v-model="searchQuery"
      :suggestions="searchSuggestions"
      @search-input="onSearchInput"
      @search-focus="onMcSearchFocus"
      @search-blur="hideMcSuggestions"
      @select="onSelectFromSearch"
    />

    <ProductFilterBar v-model="bomFilter" :options="filterOptions" />

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
import { useMaterialCalc } from '../composables/useMaterialCalc'

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
} = useMaterialCalc()

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
  padding: 6px 12px;
  margin: 0 16px 6px;
  font-size: 12px;
  color: var(--color-text-secondary);
  background: var(--color-warning-50);
  border-radius: 8px;
  text-align: center;
  flex-shrink: 0;
}
</style>
