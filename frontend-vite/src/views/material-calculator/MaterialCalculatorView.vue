<template>
  <div class="mc-container">
    <div class="mc-card mc-card-main">
      <div class="mc-card-header">
        <HeaderTabs />
        <div class="mc-header-actions">
          <span class="count-badge">已选 {{ selectedProducts.length }} 个</span>
          <button class="mc-action-btn mc-action-btn-primary" :disabled="orderItems.length === 0" @click="showBatchModal = true">
            <i class="fas fa-layer-group"  aria-hidden="true" />
            批量录入
          </button>
          <button class="mc-action-btn mc-action-btn-danger" :disabled="orderItems.length === 0" @click="clearAll">
            <i class="fas fa-eraser"  aria-hidden="true" />
            清空
          </button>
          <span v-if="calcStatus" :class="['mc-status-badge', calculating ? 'calculating' : 'done']">
            {{ calcStatus }}
          </span>
        </div>
      </div>

      <div class="mc-body">
        <!-- Column 1: Product Selection -->
        <div class="mc-col mc-col-products">
          <div class="mc-col-title">
            <i class="fas fa-boxes-stacked"  aria-hidden="true" />
            产品选择
          </div>

          <!-- Search -->
          <div class="mc-search-wrapper">
            <div class="mc-search-input-group">
              <i class="fas fa-search mc-search-icon"  aria-hidden="true" />
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
                <i class="fas fa-times"  aria-hidden="true" />
              </button>
            </div>
            <div v-if="searchSuggestions.length" class="mc-search-dropdown">
              <div v-for="p in searchSuggestions" :key="p.id" class="mc-dropdown-item" @mousedown.prevent="addProduct(p)">
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

          <!-- Product list -->
          <div class="mc-product-list">
            <div v-if="loadingProducts" class="mc-loading-state">
              <i class="fas fa-spinner fa-spin"  aria-hidden="true" />
              <span>加载中…</span>
            </div>
            <div v-else-if="filteredProducts.length === 0" class="mc-empty-state">
              <i class="fas fa-inbox"  aria-hidden="true" />
              <span>暂无产品</span>
            </div>
            <VirtualList
              :items="filteredProducts"
              :itemHeight="80"
              :containerHeight="600"
              :itemKey="(p: any) => p.id"
            >
              <template #default="{ item: p }">
                <div
                  :class="['mc-product-item', selectedProducts.includes(p.id) ? 'selected' : '']"
                  @click="toggleProduct(p)"
                >
                  <i :class="['mc-checkbox', selectedProducts.includes(p.id) ? 'fas fa-check-square' : 'far fa-square']"  aria-hidden="true" />
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
          </div>
        </div>

        <!-- Column 2: Order Quantity -->
        <div class="mc-col mc-col-orders">
          <div class="mc-col-title">
            <i class="fas fa-clipboard-check"  aria-hidden="true" />
            订单数量录入
          </div>

          <div class="mc-order-list">
            <div v-if="orderItems.length === 0" class="mc-empty-state">
              <i class="fas fa-hand-point-left"  aria-hidden="true" />
              <span>请从左侧选择产品</span>
            </div>
            <div v-for="item in orderItems" :key="item.product_id" class="mc-order-item">
              <div class="mc-order-name">
                {{ item.name }}
              </div>
              <div class="mc-order-inputs">
                <input
                  type="number"
                  class="form-number-input mc-qty-input"
                  v-model.number="item.quantity"
                  min="0"
                  step="1"
                  @input="debounceCalc"
                />
              </div>
              <button class="mc-delete-btn" @click="removeProduct(item.product_id)" aria-label="删除">
                <i class="fas fa-trash-alt"  aria-hidden="true" />
              </button>
            </div>
          </div>

          <div v-if="totalOrders > 0" class="mc-summary-panel">
            <span class="mc-summary-label">订单总数</span>
            <div class="mc-summary-value">
              <span class="mc-summary-number">{{ totalOrders }}</span>
              <span class="mc-summary-unit">件</span>
            </div>
          </div>
        </div>

        <!-- Column 3: Calculation Results -->
        <div class="mc-col mc-col-results">
          <div class="mc-col-title">
            <i class="fas fa-chart-pie"  aria-hidden="true" />
            物料用量计算结果
          </div>

          <div class="mc-result-content">
            <div v-if="!hasResults" class="mc-empty-state">
              <i class="fas fa-calculator"  aria-hidden="true" />
              <span>选择产品并输入数量后自动计算</span>
            </div>
            <div v-else>
              <div
                v-for="cat in categoryList"
                :key="cat.key"
                class="mc-category-block"
                :class="'mc-cat-' + cat.key"
              >
                <button class="mc-category-header" @click="collapsed[cat.key] = !collapsed[cat.key]">
                  <i :class="['mc-cat-icon', cat.icon]"  aria-hidden="true" />
                  <span class="mc-cat-label">{{ cat.label }}</span>
                  <span class="mc-cat-count">({{ calcResults[cat.key]?.length ?? 0 }} 项)</span>
                  <i :class="['fas fa-chevron-down mc-cat-toggle', collapsed[cat.key] ? '' : 'expanded']"  aria-hidden="true" />
                </button>

                <div v-if="!collapsed[cat.key] && calcResults[cat.key]?.length" class="mc-category-table">
                  <table>
                    <thead>
                      <tr>
                        <th style="text-align: left">供应商</th>
                        <th style="text-align: left">物料名称</th>
                        <th style="text-align: left">规格</th>
                        <th style="text-align: right">总采购量</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="(row, ri) in calcResults[cat.key]" :key="ri">
                        <td>{{ row.supplier_name || '-' }}</td>
                        <td>{{ row.material_name }}</td>
                        <td>{{ row.specification || '-' }}</td>
                        <td class="mc-qty-cell">{{ row.total_quantity }} {{ row.unit }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Batch Input Modal -->
    <UiDialog :open="showBatchModal" max-width-class="max-w-[400px]" @update:open="showBatchModal = $event">
      <template #header>
        <h3 class="text-base font-semibold text-text m-0">批量录入数量</h3>
      </template>
      <div class="py-2">
        <label class="block text-xs font-semibold text-text-secondary mb-1.5 uppercase tracking-wider"
          >统一订单数量</label
        >
        <input type="number" class="form-number-input" v-model.number="batchQuantity" min="1" step="1" style="width: 100%" />
      </div>
      <template #footer>
        <UiButton variant="ghost" size="sm" @click="showBatchModal = false"> 取消 </UiButton>
        <UiButton variant="primary" size="sm" @click="applyBatch"> 应用到全部 </UiButton>
      </template>
    </UiDialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { purchaseApi } from '@/api'
import { showToast } from '@/composables/useToast'
import UiButton from '@/components/ui/UiButton.vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import VirtualList from '@/components/ui/VirtualList.vue'
import HeaderTabs from '@/layouts/components/HeaderTabs.vue'

interface Product {
  id: number
  name: string
  barcode?: string
  has_bom: boolean
}

interface OrderItem {
  product_id: number
  name: string
  quantity: number
}

interface CalcRow {
  supplier_name: string
  material_name: string
  specification: string
  total_quantity: number
  unit: string
}

const categoryList = [
  { key: 'filling', label: '填充类', icon: 'fas fa-cloud' },
  { key: 'fabric', label: '面料类', icon: 'fas fa-scroll' },
  { key: 'accessory', label: '辅料类', icon: 'fas fa-puzzle-piece' },
]

const filterOptions: Array<{ label: string; value: 'all' | 'true' | 'false' }> = [
  { label: '全部', value: 'all' },
  { label: '有BOM', value: 'true' },
  { label: '无BOM', value: 'false' },
]

const searchQuery = ref('')
const searchSuggestions = ref<Product[]>([])
const bomFilter = ref<'all' | 'true' | 'false'>('all')
const selectedProducts = ref<number[]>([])
const orderItems = ref<OrderItem[]>([])
const calculating = ref(false)
const calcResults = ref<Record<string, CalcRow[]>>({})
const collapsed = reactive<Record<string, boolean>>({})
const showBatchModal = ref(false)
const batchQuantity = ref(1)

let searchTimer: ReturnType<typeof setTimeout> | null = null
let calcTimer: ReturnType<typeof setTimeout> | null = null

const { data: productsQueryData, isLoading: loadingProducts } = useQuery({
  queryKey: ['material-calculator-products'],
  queryFn: async () => {
    const res = (await purchaseApi.products({ per_page: 200, simple: true })) as any
    return (res.products ?? []).map((p: any) => ({
      id: p.id,
      name: p.name,
      barcode: p.barcode,
      has_bom: !!p.has_bom,
    })) as Product[]
  },
  staleTime: 30_000,
})

const allProducts = computed<Product[]>(() => productsQueryData.value ?? [])

const filteredProducts = computed(() => {
  let list = allProducts.value
  if (bomFilter.value === 'true') list = list.filter((p) => p.has_bom)
  else if (bomFilter.value === 'false') list = list.filter((p) => !p.has_bom)
  return list
})

const totalOrders = computed(() => orderItems.value.reduce((s, i) => s + i.quantity, 0))

const calcStatus = computed(() => {
  if (calculating.value) return '计算中...'
  const total = Object.values(calcResults.value).reduce((s, arr) => s + arr.length, 0)
  return total > 0 ? `${total} 种物料` : ''
})

const hasResults = computed(() => Object.values(calcResults.value).some((arr) => arr.length > 0))

function onSearchInput() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(async () => {
    if (!searchQuery.value.trim()) {
      searchSuggestions.value = []
      return
    }
    try {
      const res = (await purchaseApi.searchSuggestions(searchQuery.value.trim())) as any
      searchSuggestions.value = res.suggestions ?? []
    } catch {
      searchSuggestions.value = []
    }
  }, 250)
}

function onMcSearchFocus() {
  if (searchQuery.value.trim() && searchSuggestions.value.length === 0) {
    onSearchInput()
  }
}
function hideMcSuggestions() {
  setTimeout(() => { searchSuggestions.value = [] }, 150)
}

function toggleProduct(p: Product) {
  if (!p.has_bom) {
    showToast(`"${p.name}" 没有BOM，无法计算物料`, 'warning')
    return
  }
  if (selectedProducts.value.includes(p.id)) {
    removeProduct(p.id)
  } else {
    addProduct(p)
  }
}

function addProduct(p: Product) {
  if (!p.has_bom) {
    showToast(`"${p.name}" 没有BOM，无法计算物料`, 'warning')
    return
  }
  if (selectedProducts.value.includes(p.id)) return
  selectedProducts.value.push(p.id)
  orderItems.value.push({ product_id: p.id, name: p.name, quantity: 0 })
  searchSuggestions.value = []
  searchQuery.value = ''
  debounceCalc()
}

function removeProduct(id: number) {
  const idx = selectedProducts.value.indexOf(id)
  if (idx >= 0) selectedProducts.value.splice(idx, 1)
  const oiIdx = orderItems.value.findIndex((i) => i.product_id === id)
  if (oiIdx >= 0) orderItems.value.splice(oiIdx, 1)
  debounceCalc()
}

function applyBatch() {
  orderItems.value.forEach((i) => {
    i.quantity = batchQuantity.value
  })
  showBatchModal.value = false
  debounceCalc()
}

function clearAll() {
  selectedProducts.value = []
  orderItems.value = []
  calcResults.value = {}
}

function debounceCalc() {
  if (calcTimer) clearTimeout(calcTimer)
  calcTimer = setTimeout(() => triggerCalculation(), 350)
}

async function triggerCalculation() {
  const validOrders = orderItems.value.filter((i) => i.quantity > 0)
  if (validOrders.length === 0) {
    calcResults.value = {}
    return
  }
  calculating.value = true
  try {
    const res = (await purchaseApi.calculate(
      validOrders.map((i) => ({ product_id: i.product_id, quantity: i.quantity })),
    )) as any
    calcResults.value = {
      filling: res.filling ?? [],
      fabric: res.fabric ?? [],
      accessory: res.accessory ?? [],
      packaging: res.packaging ?? [],
    }
  } catch (err: any) {
    showToast(err?.response?.data?.detail || '计算失败', 'error')
  } finally {
    calculating.value = false
  }
}
</script>

<style scoped>
.form-number-input {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-size: 13px;
  color: var(--color-text);
  font-family: inherit;
  -moz-appearance: textfield;
}
.form-number-input::-webkit-inner-spin-button,
.form-number-input::-webkit-outer-spin-button {
  opacity: 1;
}
.form-number-input:focus {
  outline: none;
  border-color: var(--color-primary-500);
  box-shadow: 0 0 0 3px rgba(91, 141, 239, 0.15);
}
.form-number-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
/* === Layout === */
.mc-container {
  padding: 8px;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* === Main Card === */
.mc-card {
  background: white;
  border-radius: 18px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  transition: box-shadow 0.4s cubic-bezier(0.4, 0, 0.2, 1), transform 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
}

.mc-card:hover {
  box-shadow: 0 4px 12px rgba(0,0,0,0.06);
  transform: translateY(-2px);
}

.mc-card-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.mc-card-header {
  display: flex;
  flex-wrap: nowrap;
  justify-content: space-between;
  align-items: center;
  padding: 10px 24px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  gap: 12px;
}
.mc-card-header :deep(.ht-bar) {
  width: auto;
  margin: 0;
}

.mc-card-title-group {
  display: flex;
  align-items: center;
  gap: 14px;
}

.mc-card-title-group h3 {
  font-size: 17px;
  font-weight: 700;
  color: var(--color-text);
  margin: 0;
}

.mc-card-title-group small {
  font-size: 12px;
  color: var(--color-text-secondary);
  display: block;
  margin-top: 2px;
}

/* === Three Column Body === */
.mc-body {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.mc-col {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.mc-col + .mc-col {
  border-left: 1px solid var(--color-border-light, #f1f5f9);
}

.mc-col-title {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 20px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  flex-shrink: 0;
}

.mc-col-title i {
  font-size: 14px;
  color: var(--color-primary-500);
}

/* === Icon Boxes === */
.mc-icon-box {
  width: 46px;
  height: 46px;
  border-radius: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 19px;
}

.mc-icon-blue {
  background: linear-gradient(135deg, var(--color-primary-100), var(--color-primary-200));
  color: var(--color-primary-700);
}

.mc-icon-green {
  background: linear-gradient(135deg, var(--color-success-100), var(--color-success-200));
  color: var(--color-success-700);
}

.mc-icon-purple {
  background: linear-gradient(135deg, var(--color-purple-100, #e1bee7), var(--color-purple-200, #ce93d8));
  color: var(--color-purple-800);
}

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

/* === Order Items === */
.mc-header-actions {
  display: flex;
  gap: 8px;
}

.mc-action-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: border-color 0.3s ease, background 0.3s ease, transform 0.3s ease;
  background: white;
}

.mc-action-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.mc-action-btn i {
  font-size: 11px;
}

.mc-action-btn-primary {
  color: var(--color-primary-600);
}

.mc-action-btn-primary:hover:not(:disabled) {
  background: var(--color-primary-50);
  border-color: var(--color-primary-300);
  transform: translateY(-1px);
}

.mc-action-btn-danger {
  color: var(--color-danger-500);
}

.mc-action-btn-danger:hover:not(:disabled) {
  background: var(--color-danger-50);
  border-color: var(--color-danger-200);
  transform: translateY(-1px);
}

.mc-order-list {
  padding: 12px 16px;
  min-height: 60px;
  flex: 1;
  overflow-y: auto;
}

.mc-order-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  margin-bottom: 8px;
  background: white;
  transition: border-color 0.3s ease, transform 0.3s ease, box-shadow 0.3s ease;
}

.mc-order-item:hover {
  border-color: var(--color-primary-300);
  transform: translateY(-1px);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}

.mc-order-name {
  flex: 1;
  font-weight: 650;
  font-size: 14px;
  color: var(--color-text);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mc-order-inputs {
  display: flex;
  gap: 8px;
  align-items: center;
}

.mc-qty-input {
  width: 110px;
}

.mc-delete-btn {
  background: none;
  border: none;
  color: var(--color-text-muted, #94a3b8);
  cursor: pointer;
  padding: 8px;
  border-radius: 8px;
  transition: background 0.2s, color 0.2s;
  font-size: 13px;
}

.mc-delete-btn:hover {
  background: var(--color-danger-50);
  color: var(--color-danger-500);
}

/* === Summary Panel === */
.mc-summary-panel {
  margin: 0 16px 12px;
  padding: 10px 14px;
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  border-radius: 13px;
  border: 1px solid var(--color-primary-200);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.mc-summary-label {
  font-size: 13px;
  color: var(--color-text-secondary);
  font-weight: 500;
}

.mc-summary-value {
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.mc-summary-number {
  font-size: 32px;
  font-weight: 800;
  color: var(--color-primary-600);
  line-height: 1;
}

.mc-summary-unit {
  font-size: 14px;
  color: var(--color-primary-500);
  font-weight: 500;
}

/* === Status Badge === */
.mc-status-badge {
  padding: 5px 12px;
  border-radius: 16px;
  font-size: 12px;
  font-weight: 600;
}

.mc-status-badge.calculating {
  background: var(--color-warning-50);
  color: var(--color-warning-600);
}

.mc-status-badge.done {
  background: var(--color-success-50);
  color: var(--color-success-600);
}

/* === Results === */
.mc-result-content {
  padding: 16px;
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}

.mc-category-block {
  margin-bottom: 16px;
}

.mc-category-header {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-radius: 11px;
  border: none;
  cursor: pointer;
  transition: background 0.3s ease;
  text-align: left;
}

.mc-cat-icon {
  font-size: 15px;
}

.mc-cat-label {
  font-size: 14px;
  font-weight: 700;
}

.mc-cat-count {
  font-size: 12px;
  color: var(--color-text-secondary);
}

.mc-cat-toggle {
  margin-left: auto;
  font-size: 11px;
  color: var(--color-text-muted, #94a3b8);
  transition: transform 0.25s ease;
}

.mc-cat-toggle.expanded {
  transform: rotate(180deg);
}

/* Category color variants */
.mc-cat-filling .mc-category-header {
  background: linear-gradient(135deg, var(--color-info-50), var(--color-surface-card));
}

.mc-cat-filling .mc-cat-icon,
.mc-cat-filling .mc-cat-label {
  color: var(--color-primary-700);
}

.mc-cat-fabric .mc-category-header {
  background: linear-gradient(135deg, var(--color-success-50), var(--color-surface-card));
}

.mc-cat-fabric .mc-cat-icon,
.mc-cat-fabric .mc-cat-label {
  color: var(--color-success-700);
}

.mc-cat-accessory .mc-category-header {
  background: linear-gradient(135deg, var(--color-warning-50), var(--color-surface-card));
}

.mc-cat-accessory .mc-cat-icon,
.mc-cat-accessory .mc-cat-label {
  color: var(--color-warning-800);
}

.mc-cat-packaging .mc-category-header {
  background: linear-gradient(135deg, var(--color-purple-50), var(--color-surface-card));
}

.mc-cat-packaging .mc-cat-icon,
.mc-cat-packaging .mc-cat-label {
  color: var(--color-purple-800);
}

.mc-category-table {
  margin-top: 8px;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid var(--color-border-light, #e2e8f0);
}

.mc-category-table table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.mc-category-table thead th {
  padding: 10px 14px;
  background: var(--color-surface, #f8fafc);
  font-weight: 600;
  color: var(--color-text-secondary);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 2px solid var(--color-border-light, #e2e8f0);
}

.mc-category-table tbody td {
  padding: 10px 14px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  color: var(--color-text);
  vertical-align: middle;
}

.mc-category-table tbody tr:last-child td {
  border-bottom: none;
}

.mc-category-table tbody tr:hover {
  background: var(--color-surface, #f8fafc);
}

.mc-qty-cell {
  text-align: right;
  font-weight: 600;
  white-space: nowrap;
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
