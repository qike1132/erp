<template>
  <div class="m-page">
    <MobileNavBar title="物料计算器" :show-back="true">
      <template #right>
        <button class="m-nav-btn" @click="handleCalculate" :disabled="calculating" :aria-label="calculating ? '计算中...' : '计算'">
          {{ calculating ? '计算中...' : '计算' }}
        </button>
      </template>
    </MobileNavBar>
    <div class="m-page-body">
      <MSearchBar v-model="searchQuery" placeholder="搜索产品名称/条码..." />

      <div class="m-section-header">
        <span class="m-section-title">已选产品 ({{ orderItems.length }})</span>
        <button v-if="orderItems.length" class="m-text-btn" @click="clearAll">清空</button>
      </div>

      <MEmpty v-if="!orderItems.length" title="请搜索并添加产品" subtitle="输入产品名称后选择，设置采购数量" />

      <MList v-else>
        <div v-for="item in orderItems" :key="item.product_id" class="m-calc-item">
          <div class="m-calc-info">
            <div class="m-calc-name">{{ item.name }}</div>
          </div>
          <div class="m-calc-qty">
            <button class="m-qty-btn" @click="decQty(item)">−</button>
            <input v-model.number="item.quantity" type="number" min="0" class="m-qty-input" @input="onQtyInput(item)" />
            <button class="m-qty-btn" @click="incQty(item)">+</button>
            <button class="m-del-btn" @click="removeProduct(item.product_id)">✕</button>
          </div>
        </div>
      </MList>

      <div v-if="calcResults && Object.keys(calcResults).length" class="m-results">
        <h3 class="m-results-title">计算结果</h3>
        <div v-for="(rows, category) in calcResults" :key="category" class="m-result-group">
          <div class="m-result-cat" @click="toggleCategory(category as string)">
            <span>{{ categoryLabel(category as string) }} ({{ rows.length }})</span>
            <svg :style="{ transform: collapsed[category as string] ? '' : 'rotate(90deg)' }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><polyline points="9 18 15 12 9 6"/></svg>
          </div>
          <template v-if="!collapsed[category as string]">
            <div v-for="row in rows" :key="row.material_name" class="m-result-row">
              <div class="m-result-name">{{ row.material_name }}</div>
              <div class="m-result-meta">{{ row.supplier_name }} · {{ row.specification || '—' }}</div>
              <div class="m-result-qty">{{ row.total_quantity }} {{ row.unit }}</div>
            </div>
          </template>
        </div>
      </div>

      <MBottomSheet v-model:visible="searchSheetVisible" title="选择产品">
        <MSearchBar v-model="searchQuery" placeholder="搜索产品..." />
        <div v-if="searchLoading" class="m-center"><MSpinner /></div>
        <MList v-else-if="searchResults.length">
          <MListItem
            v-for="p in searchResults"
            :key="p.id"
            :title="p.name"
            :subtitle="p.barcode || ''"
            @click="addProduct(p)"
          />
        </MList>
      </MBottomSheet>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, watch, onUnmounted } from 'vue'
import { purchaseApi, type MaterialCalcProduct } from '@/api'
import {
  useMaterialCalculator,
  CALC_CATEGORY_LABELS,
  clampQuantity,
} from '@/composables/useMaterialCalculator'
import MobileNavBar from '@/mobile/layouts/components/MobileNavBar.vue'
import MSearchBar from '@/mobile/components/MSearchBar.vue'
import MList from '@/mobile/components/MList.vue'
import MListItem from '@/mobile/components/MListItem.vue'
import MEmpty from '@/mobile/components/MEmpty.vue'
import MSpinner from '@/mobile/components/MSpinner.vue'
import MBottomSheet from '@/mobile/components/MBottomSheet.vue'

const {
  orderItems,
  calcResults,
  calculating,
  addProduct: addProductToOrder,
  removeProduct,
  clearAll,
  triggerCalculation,
  dispose,
} = useMaterialCalculator()

const searchQuery = ref('')
const searchResults = ref<MaterialCalcProduct[]>([])
const searchLoading = ref(false)
const searchSheetVisible = ref(false)
const collapsed = reactive<Record<string, boolean>>({})

let searchTimer: ReturnType<typeof setTimeout> | null = null
watch(searchQuery, (q) => {
  if (searchTimer) clearTimeout(searchTimer)
  if (!q) { searchResults.value = []; return }
  searchTimer = setTimeout(async () => {
    searchLoading.value = true
    try {
      const res = await purchaseApi.searchSuggestions(q)
      searchResults.value = res.suggestions ?? []
    } finally { searchLoading.value = false }
  }, 300)
})

onUnmounted(() => { if (searchTimer) clearTimeout(searchTimer); dispose() })

function addProduct(p: MaterialCalcProduct) {
  // 移动端 +/- 按钮 UI，默认数量 1（桌面端用数字输入框，默认 0）
  if (addProductToOrder(p, 1)) {
    searchSheetVisible.value = false
  }
}

function handleCalculate() {
  if (!orderItems.value.length) return
  triggerCalculation()
}

// S7: 数量规整为非负整数
function onQtyInput(item: { quantity: number }) {
  item.quantity = clampQuantity(item.quantity)
}
function incQty(item: { quantity: number }) {
  item.quantity = clampQuantity(item.quantity) + 1
}
function decQty(item: { quantity: number }) {
  item.quantity = Math.max(0, clampQuantity(item.quantity) - 1)
}

function toggleCategory(cat: string) { collapsed[cat] = !collapsed[cat] }
function categoryLabel(cat: string) {
  return CALC_CATEGORY_LABELS[cat] || cat
}
</script>

<style scoped>
.m-page { display: flex; flex-direction: column; height: 100%; background: var(--m-bg-deep); }
.m-page-body { flex: 1; min-height: 0; overflow-y: auto; padding: var(--m-gap-md); padding-bottom: calc(var(--m-gap-lg) + var(--m-tabbar-safe)); -webkit-overflow-scrolling: touch; }
.m-nav-btn { padding: 6px 14px; border: none; border-radius: 8px; background: var(--m-accent); color: white; font-size: 14px; font-weight: 600; cursor: pointer; font-family: inherit; }
.m-nav-btn:disabled { opacity: 0.5; }
.m-section-header { display: flex; justify-content: space-between; align-items: center; margin: 16px 0 8px; }
.m-section-title { font-size: 15px; font-weight: 600; color: var(--m-text-primary); }
.m-text-btn { border: none; background: none; color: var(--m-accent-rose); font-size: 14px; font-weight: 500; cursor: pointer; font-family: inherit; }
.m-calc-item { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; border-bottom: 0.5px solid rgba(0,0,0,0.04); }
.m-calc-name { font-size: 15px; font-weight: 500; color: var(--m-text-primary); }
.m-calc-qty { display: flex; align-items: center; gap: 4px; }
.m-qty-btn { width: 28px; height: 28px; border: none; border-radius: 6px; background: var(--m-bg-grouped); font-size: 16px; cursor: pointer; display: flex; align-items: center; justify-content: center; font-family: inherit; }
.m-qty-input { width: 44px; height: 28px; text-align: center; border: none; background: var(--m-bg-grouped); border-radius: 6px; font-size: 14px; font-family: inherit; }
.m-del-btn { width: 28px; height: 28px; border: none; background: none; color: var(--m-accent-rose); font-size: 14px; cursor: pointer; margin-left: 4px; }
.m-results { margin-top: 20px; }
.m-results-title { font-size: 17px; font-weight: 700; color: var(--m-text-primary); margin: 0 0 10px; }
.m-result-group { background: var(--m-bg-card); border-radius: var(--m-radius-md); box-shadow: var(--m-shadow-card); margin-bottom: 10px; overflow: hidden; }
.m-result-cat { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; font-size: 14px; font-weight: 600; color: var(--m-text-primary); cursor: pointer; }
.m-result-row { padding: 8px 16px; border-top: 0.5px solid rgba(0,0,0,0.04); }
.m-result-name { font-size: 14px; font-weight: 500; color: var(--m-text-primary); }
.m-result-meta { font-size: 12px; color: var(--m-text-secondary); }
.m-result-qty { font-size: 14px; font-weight: 600; color: var(--m-accent); margin-top: 2px; }
.m-center { display: flex; justify-content: center; padding: 24px 0; }
</style>
