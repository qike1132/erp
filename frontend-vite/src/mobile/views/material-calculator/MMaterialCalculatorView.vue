<template>
  <div class="m-page">
    <MobileNavBar title="物料计算器" :show-back="true">
      <template #right>
        <button class="m-nav-btn" :disabled="calculating" :aria-label="calculating ? '计算中...' : '计算'" @click="handleCalculate">
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

      <!-- 分块结果：首张「汇总」卡（多 SKU 时）+ 各产品作用域卡（默认 BOM 恒首） -->
      <div v-if="hasGroups" class="m-results">
        <h3 class="m-results-title">计算结果</h3>

        <!-- 汇总卡：相同供应商·物料·规格跨产品合并求和（方案 A 移动端） -->
        <div v-if="calcGroups.length > 1" class="m-scope-card m-summary-card">
          <div class="m-scope-head">
            <span class="m-scope-badge is-summary">汇总</span>
            <span class="m-scope-name">{{ summary.productCount }} 个产品</span>
            <span class="m-scope-qty">合计 {{ summary.totalQuantity }} 件</span>
          </div>
          <div v-for="cat in categoryList" :key="cat.key" class="m-result-group">
            <div class="m-result-cat" @click="toggle(`summary::${cat.key}`)">
              <span>{{ cat.label }} ({{ summaryCat(cat.key).length }})</span>
              <svg :style="{ transform: isCollapsed(`summary::${cat.key}`) ? '' : 'rotate(90deg)' }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><polyline points="9 18 15 12 9 6" /></svg>
            </div>
            <template v-if="!isCollapsed(`summary::${cat.key}`)">
              <div
                v-for="row in summaryCat(cat.key)"
                :key="`summary::${cat.key}::${rowKeyOf('summary', cat.key, row)}`"
                class="m-result-row"
              >
                <div class="m-result-name">
                  {{ row.material_name || row.name }}<span v-if="row.sku_count > 1" class="m-sku-badge">{{ row.sku_count }} 个SKU</span>
                </div>
                <div class="m-result-meta">{{ row.supplier_name }} · {{ row.specification || '—' }}</div>
                <div class="m-result-qty">{{ row.total_quantity }} {{ row.unit }}</div>
              </div>
            </template>
          </div>
        </div>

        <div v-for="(group, gi) in calcGroups" :key="scopeKeyOf(group)" class="m-scope-card">
          <div class="m-scope-head">
            <span class="m-scope-badge" :class="group.role_id == null ? 'is-default' : 'is-role'">
              {{ group.role_id == null ? '默认' : '#' + (gi + 1) }}
            </span>
            <span class="m-scope-name">{{ scopeNameOf(group) }}</span>
            <span class="m-scope-qty">×{{ group.quantity }}</span>
          </div>
          <div v-for="cat in categoryList" :key="cat.key" class="m-result-group">
            <div class="m-result-cat" @click="toggle(`${scopeKeyOf(group)}::${cat.key}`)">
              <span>{{ cat.label }} ({{ groupCat(group, cat.key).length }})</span>
              <svg :style="{ transform: isCollapsed(`${scopeKeyOf(group)}::${cat.key}`) ? '' : 'rotate(90deg)' }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><polyline points="9 18 15 12 9 6" /></svg>
            </div>
            <template v-if="!isCollapsed(`${scopeKeyOf(group)}::${cat.key}`)">
              <div
                v-for="row in groupCat(group, cat.key)"
                :key="rowKeyOf(scopeKeyOf(group), cat.key, row)"
                class="m-result-row"
              >
                <div class="m-result-name">{{ row.material_name || row.name }}</div>
                <div class="m-result-meta">{{ row.supplier_name }} · {{ row.specification || '—' }}</div>
                <div class="m-result-qty">{{ row.total_quantity }} {{ row.unit }}</div>
              </div>
            </template>
          </div>
        </div>
      </div>

      <!-- 扁平回退（旧后端 / groups 缺失，A-5） -->
      <div v-else-if="hasFlat" class="m-results">
        <h3 class="m-results-title">计算结果</h3>
        <div v-for="cat in categoryList" :key="cat.key" class="m-result-group">
          <div class="m-result-cat" @click="toggle(`flat::${cat.key}`)">
            <span>{{ cat.label }} ({{ (calcResults[cat.key] || []).length }})</span>
            <svg :style="{ transform: isCollapsed(`flat::${cat.key}`) ? '' : 'rotate(90deg)' }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><polyline points="9 18 15 12 9 6" /></svg>
          </div>
          <template v-if="!isCollapsed(`flat::${cat.key}`)">
            <div v-for="row in (calcResults[cat.key] || [])" :key="rowKeyOf('flat', cat.key, row)" class="m-result-row">
              <div class="m-result-name">{{ row.material_name || row.name }}</div>
              <div class="m-result-meta">{{ row.supplier_name }} · {{ row.specification || '—' }}</div>
              <div class="m-result-qty">{{ row.total_quantity }} {{ row.unit }}</div>
            </div>
          </template>
        </div>
      </div>

      <!-- 跨作用域对比矩阵：窄屏横向滚动 + 首列吸附（保留并排对比价值，A-12） -->
      <div v-if="matrix.visible" class="m-matrix">
        <h3 class="m-results-title">跨作用域对比</h3>
        <div class="m-matrix-scroll">
          <table class="m-matrix-table">
            <thead>
              <tr>
                <th class="m-mx-name-col">物料</th>
                <th>单位</th>
                <th v-for="s in matrix.scopes" :key="s.key" class="m-mx-num">{{ s.roleName }}</th>
                <th class="m-mx-num m-mx-total">合计</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in matrix.rows" :key="row.key" :class="{ 'm-mx-split': row.unitConflict }">
                <td class="m-mx-name-col">
                  {{ row.materialName }}<span v-if="row.specification" class="m-mx-spec"> · {{ row.specification }}</span>
                </td>
                <td>{{ row.unit || '—' }}</td>
                <td v-for="s in matrix.scopes" :key="s.key" class="m-mx-num">{{ cellText(row, s.key) }}</td>
                <td class="m-mx-num m-mx-total">{{ numText(row.total) }} {{ row.unit }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <div v-else-if="matrix.reason === 'single-scope'" class="m-matrix-hint">仅 1 个作用域，无需跨作用域对比</div>

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
import { ref, reactive, computed, watch, onUnmounted } from 'vue'
import { purchaseApi, type MaterialCalcProduct, type MaterialCalcRow, type MaterialCalcScopeGroup } from '@/api'
import {
  useMaterialCalculator,
  CALC_CATEGORY_LIST,
  clampQuantity,
} from '@/composables/useMaterialCalculator'
import { scopeKeyOf, scopeNameOf, type MatrixRow } from '@/utils/roleMatrix'
import { deriveCalcSummary, type SummaryRow } from '@/utils/calcSummary'
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
  calcGroups,
  calculating,
  matrix,
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

const categoryList = CALC_CATEGORY_LIST
const hasGroups = computed(() => calcGroups.value.length > 0)
const hasFlat = computed(() => Object.values(calcResults.value).some((arr) => arr.length > 0))

/** 全产品汇总（方案 A 移动端）：相同供应商·物料·规格合并求和，仅多 SKU 时展示。 */
const summary = computed(() => deriveCalcSummary(calcGroups.value))

/** 汇总卡里某分类的行（安全索引）。 */
function summaryCat(category: string): SummaryRow[] {
  const rows = summary.value.rows as Record<string, SummaryRow[] | undefined>
  return rows[category] ?? []
}

let searchTimer: ReturnType<typeof setTimeout> | null = null
watch(searchQuery, (q) => {
  if (searchTimer) clearTimeout(searchTimer)
  if (!q) { searchResults.value = []; return }
  searchTimer = setTimeout(async () => {
    searchLoading.value = true
    try {
      const res = await purchaseApi.searchSuggestions(q)
      searchResults.value = res.suggestions ?? []
    } catch { searchResults.value = [] } finally { searchLoading.value = false }
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

function toggle(key: string) { collapsed[key] = !collapsed[key] }
function isCollapsed(key: string): boolean { return !!collapsed[key] }

/** 读取分块里某分类的行（安全索引）。 */
function groupCat(group: MaterialCalcScopeGroup, category: string): MaterialCalcRow[] {
  const record = group as unknown as Record<string, MaterialCalcRow[] | undefined>
  const value = record[category]
  return Array.isArray(value) ? value : []
}

/** 复合 row-key（A-9）：同分类同名不同规格/供应商/单位必须全部渲染。 */
function rowKeyOf(prefix: string, category: string, row: MaterialCalcRow): string {
  return [prefix, category, row.material_name || row.name || '', row.specification || '', row.supplier_name || '', row.unit || ''].join('|')
}

/** 矩阵数值：整数原样，非整数最多 3 位小数去尾零。 */
function numText(v: number): string {
  return Number.isInteger(v) ? String(v) : String(parseFloat(v.toFixed(3)))
}
function cellText(row: MatrixRow, scopeKey: string): string {
  const v = row.cells[scopeKey]
  return v == null ? '—' : numText(v)
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

/* 作用域分块卡 */
.m-scope-card { background: var(--m-bg-card); border-radius: var(--m-radius-md); box-shadow: var(--m-shadow-card); margin-bottom: 12px; padding: 10px; }
.m-scope-head { display: flex; align-items: center; gap: 8px; padding: 2px 4px 10px; }
.m-scope-badge { min-width: 30px; text-align: center; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 700; color: #fff; }
.m-scope-badge.is-default { background: var(--m-text-secondary); }
.m-scope-badge.is-role { background: var(--m-accent); }
/* 汇总卡徽标：与作用域徽标区分（灰底主色字，跨产品合并的标识） */
.m-scope-badge.is-summary { background: var(--m-text-secondary); }
.m-sku-badge {
  display: inline-block; margin-left: 5px; padding: 1px 6px; border-radius: 999px;
  background: rgba(91, 141, 239, 0.12); color: #2d5ab8;
  font-size: 10px; font-weight: 700; vertical-align: 1px;
}
.m-scope-name { font-size: 14px; font-weight: 700; color: var(--m-text-primary); }
.m-scope-qty { margin-left: auto; font-size: 12px; font-weight: 600; color: var(--m-accent); }

.m-result-group { background: var(--m-bg-card); border-radius: var(--m-radius-md); margin-bottom: 8px; overflow: hidden; }
.m-result-cat { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; font-size: 14px; font-weight: 600; color: var(--m-text-primary); cursor: pointer; }
.m-result-row { padding: 8px 16px; border-top: 0.5px solid rgba(0,0,0,0.04); }
.m-result-name { font-size: 14px; font-weight: 500; color: var(--m-text-primary); }
.m-result-meta { font-size: 12px; color: var(--m-text-secondary); }
.m-result-qty { font-size: 14px; font-weight: 600; color: var(--m-accent); margin-top: 2px; }
.m-center { display: flex; justify-content: center; padding: 24px 0; }

/* 跨作用域对比矩阵：横向滚动 + 首列吸附 */
.m-matrix { margin-top: 20px; }
.m-matrix-scroll { overflow-x: auto; -webkit-overflow-scrolling: touch; border-radius: var(--m-radius-md); background: var(--m-bg-card); box-shadow: var(--m-shadow-card); }
.m-matrix-table { border-collapse: collapse; font-size: 12px; white-space: nowrap; }
.m-matrix-table th,
.m-matrix-table td { padding: 8px 10px; border-bottom: 0.5px solid rgba(0,0,0,0.05); text-align: left; }
.m-matrix-table thead th { font-weight: 700; color: var(--m-text-secondary); }
.m-mx-name-col { position: sticky; left: 0; background: var(--m-bg-card); z-index: 1; max-width: 150px; white-space: normal; color: var(--m-text-primary); }
.m-mx-spec { color: var(--m-text-secondary); }
.m-mx-num { text-align: right; font-variant-numeric: tabular-nums; }
.m-mx-total { font-weight: 700; color: var(--m-accent); }
.m-mx-split td { background: rgba(217, 119, 6, 0.06); }
.m-matrix-hint { margin-top: 16px; font-size: 12px; color: var(--m-text-secondary); }
</style>
