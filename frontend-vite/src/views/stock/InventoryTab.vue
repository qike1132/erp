<template>
  <div class="sk-inventory">
    <div class="sk-filter-bar">
      <div class="sk-filter-field">
        <label class="sk-filter-label">产品名称/69码</label>
        <input v-model="filters.product" class="sk-filter-input" placeholder="输入产品名称或69码" @keyup.enter="handleSearch()" />
      </div>
      <div class="sk-filter-actions">
        <button class="sk-action-btn sk-action-primary" @click="handleSearch()">
          <FontAwesomeIcon icon="search" style="margin-right: 4px"  aria-hidden="true" />查询
        </button>
        <button class="sk-action-btn" @click="handleReset()" aria-label="刷新">
          <FontAwesomeIcon icon="redo" aria-hidden="true" />
        </button>
      </div>
      <div v-if="inventory.length" class="sk-stat-row">
        <div class="sk-stat-card sk-stat-primary">
          <div class="sk-stat-value">{{ totalRegularQty }}</div>
          <div class="sk-stat-label">常规订单</div>
        </div>
        <div class="sk-stat-card sk-stat-warning">
          <div class="sk-stat-value">{{ totalCustomQty }}</div>
          <div class="sk-stat-label">定制订单</div>
        </div>
        <div class="sk-stat-card sk-stat-success">
          <div class="sk-stat-value">{{ totalStockinQty }}</div>
          <div class="sk-stat-label">备货数量</div>
        </div>
        <div class="sk-stat-card sk-stat-info">
          <div class="sk-stat-value">{{ totalRegularQty + totalCustomQty + totalStockinQty }}</div>
          <div class="sk-stat-label">总订单</div>
        </div>
        <div class="sk-stat-card sk-stat-stock">
          <div class="sk-stat-value">{{ totalAvailableStock }}</div>
          <div class="sk-stat-label">可用库存</div>
        </div>
      </div>
    </div>

    <div v-if="allCustomers.length" class="sk-customer-bar">
      <div class="sk-customer-bar-inner">
        <span class="sk-customer-bar-label"><FontAwesomeIcon icon="users" aria-hidden="true" /> 客户</span>
        <div class="sk-customer-scroll">
          <button
            type="button"
            :class="['sk-customer-chip', { active: !filters.customer }]"
            @click="selectCustomer('')"
          >
            <FontAwesomeIcon icon="th-large" aria-hidden="true" />全部
          </button>
          <button
            type="button"
            v-for="c in allCustomers"
            :key="c"
            :class="['sk-customer-chip', { active: filters.customer === c }]"
            @click="selectCustomer(c)"
          >{{ c }}</button>
        </div>
        <Transition name="sk-bar-fade">
          <div v-if="isFetching" class="sk-customer-loading">
            <FontAwesomeIcon icon="circle-notch" class="fa-spin" aria-hidden="true" />
          </div>
        </Transition>
      </div>
    </div>

    <div class="sk-card-main">
      <div v-if="isLoading && inventory.length === 0" class="sk-empty">
        <UiSpinner />
      </div>
      <div v-else-if="inventory.length === 0" class="sk-empty">
        <FontAwesomeIcon icon="warehouse" aria-hidden="true" />
        <span>暂无库存数据</span>
      </div>
      <template v-else>
        <div v-if="isFetching" class="sk-fetching-bar"><div class="sk-fetching-progress" /></div>
        <table class="sk-table">
          <thead>
            <tr>
              <th>客户</th>
              <th class="sk-th-left">产品名称</th>
              <th>订单数量</th>
              <th>定制订单</th>
              <th>备货数量</th>
              <th>总订单</th>
              <th>实时可用库存</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in inventory" :key="`${item.customer}-${item.product_name}`">
              <td>
                <span class="sk-customer-cell">
                  <FontAwesomeIcon icon="building" aria-hidden="true" />
                  {{ item.customer }}
                </span>
              </td>
              <td class="sk-td-left">
                <span class="sk-product-cell">
                  <FontAwesomeIcon icon="cube" aria-hidden="true" />
                  <strong>{{ item.product_name }}</strong>
                </span>
              </td>
              <td>{{ item.order_quantity }}</td>
              <td>
                <div v-if="item._custom_details && item._custom_details.length" class="sk-custom-orders">
                  <template v-for="d in item._custom_details" :key="d.country">
                    <span class="sk-custom-country">{{ d.country }}：</span><span>{{ d.qty }}</span>
                  </template>
                </div>
              </td>
              <td>{{ item.stockin_quantity }}</td>
              <td>
                <strong :class="(item.total_stock ?? 0) < 0 ? 'sk-text-negative' : 'sk-text-positive'">{{ item.total_stock ?? 0 }}</strong>
              </td>
              <td>
                <div class="sk-available-cell">
                  <strong :class="(item.available_stock ?? 0) < 0 ? 'sk-text-negative' : 'sk-text-positive'">{{ item.available_stock ?? 0 }}</strong>
                  <div v-if="item._country_available && item._country_available.length" class="sk-country-share">
                    <template v-for="d in item._country_available" :key="`${d.country}-${d.qty}`">
                      <span class="sk-country-share-label">{{ d.country }}：</span><span>{{ d.qty }}</span>
                    </template>
                  </div>
                </div>
              </td>
            </tr>
          </tbody>
        </table>

        <UiPagination v-if="totalItems > perPage" :current-page="currentPage" :total-pages="totalPages" :total-items="totalItems" @update:current-page="goPage" />
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, computed, watch, ref } from 'vue'
import { useQuery, keepPreviousData } from '@tanstack/vue-query'
import { stockApi } from '@/api'
import UiPagination from '@/components/ui/UiPagination.vue'
import { useDebouncedRef } from '@/composables/useDebouncedRef'

const filters = reactive({ customer: '', product: '', country: '' })
const debouncedProduct = useDebouncedRef(computed(() => filters.product), 300)
const page = ref(1)
const currentPage = computed(() => page.value)
const perPage = computed(() => invData.value?.per_page ?? 15)
const totalItems = computed(() => invData.value?.total_items ?? 0)
const totalPages = computed(() => Math.max(1, Math.ceil(totalItems.value / perPage.value)))

const {
  data: invData,
  isLoading,
  isFetching,
  refetch,
} = useQuery({
  queryKey: ['inventory', () => filters.customer, debouncedProduct, () => filters.country, () => page.value],
  queryFn: () =>
    stockApi.inventory({
      customer: filters.customer || undefined,
      product: debouncedProduct.value || undefined,
      country: filters.country || undefined,
      page: page.value,
      per_page: 15,
    }),
  staleTime: 30_000,
  gcTime: 60_000,
  placeholderData: keepPreviousData,
})

const inventory = computed(() => {
  const raw = invData.value?.data ?? []
  return raw.map((item) => {
    if (item._custom_details) return item
    const co = item.country_orders ?? {}
    const details: { country: string; qty: number }[] = []
    for (const [k, v] of Object.entries(co)) {
      if (k !== '常规' && v) details.push({ country: k, qty: Number(v) })
    }
    const abc = item.available_stock_by_country ?? {}
    const country_available: { country: string; qty: number }[] = []
    for (const [k, v] of Object.entries(abc)) {
      if (v) country_available.push({ country: k, qty: Number(v) })
    }
    return { ...item, _custom_details: details, _country_available: country_available }
  })
})
const allCustomers = computed(() => (invData.value?.all_customers ?? []) as string[])

const totalOrderQty = computed(() => invData.value?.total_order_quantity ?? 0)
const totalRegularQty = computed(() => Math.max(0, totalOrderQty.value - totalCustomQty.value))
const totalCustomQty = computed(() => {
  return inventory.value.reduce((s, i) => {
    const details = i._custom_details ?? []
    return s + details.reduce((ss, d) => ss + d.qty, 0)
  }, 0)
})
const totalStockinQty = computed(() => invData.value?.total_stockin_quantity ?? 0)
const totalAvailableStock = computed(() => invData.value?.total_available_stock ?? 0)

function toggleCustomer(c: string) {
  filters.customer = filters.customer === c ? '' : c
}
function selectCustomer(c: string) {
  filters.customer = c
}
function handleSearch() {
  refetch()
}
function handleReset() {
  filters.customer = ''
  filters.product = ''
  filters.country = ''
  refetch()
}
function goPage(p: number) {
  page.value = p
}
async function handleExport() {
  try {
    await stockApi.exportInventory({ customer: filters.customer, product: filters.product })
  } catch (_e) { /* error handled by interceptor */ }
}

watch(() => [filters.customer, filters.country, debouncedProduct.value], () => {
  page.value = 1
})

defineExpose({ inventory, filteredInventory: inventory, handleExport })
</script>

<style scoped>
.sk-inventory {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.sk-filter-bar {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: flex-end;
  padding: 12px 24px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
}
.sk-filter-field { flex-shrink: 0; }
.sk-filter-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  margin-bottom: 4px;
}
.sk-filter-input {
  width: 240px;
  padding: 8px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  font-size: 13px;
  outline: none;
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
  font-family: inherit;
  color: var(--color-text);
  background: white;
}
.sk-filter-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.sk-filter-input:focus {
  border-color: var(--color-primary-400);
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.sk-filter-actions {
  display: flex;
  gap: 8px;
  align-items: flex-end;
}
.sk-action-btn {
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
}
.sk-action-primary { color: var(--color-primary-600); }
.sk-action-primary:hover { background: var(--color-primary-50); border-color: var(--color-primary-300); transform: translateY(-1px); }
/* ===== 客户快捷切换栏 ===== */
.sk-customer-bar {
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  background: linear-gradient(to bottom, var(--color-surface, #f8fafc), white);
}
.sk-customer-bar-inner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 24px;
  position: relative;
}
.sk-customer-bar-label {
  font-size: 12px;
  font-weight: 700;
  color: var(--color-text-secondary);
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 5px;
  flex-shrink: 0;
}
.sk-customer-bar-label i {
  color: var(--color-primary-500);
  font-size: 13px;
}
.sk-customer-scroll {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  overflow-y: hidden;
  flex: 1;
  min-height: 0;
  padding: 2px 0;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
}
.sk-customer-scroll::-webkit-scrollbar {
  display: none;
}
.sk-customer-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 16px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  border: 2px solid var(--color-border-light, #e2e8f0);
  background: white;
  color: var(--color-text-secondary);
  white-space: nowrap;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  user-select: none;
  font-family: inherit;
  line-height: inherit;
  flex-shrink: 0;
  position: relative;
}
.sk-customer-chip i {
  font-size: 11px;
  transition: transform 0.25s ease;
}
.sk-customer-chip:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-600);
  background: var(--color-primary-50);
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}
.sk-customer-chip:hover i {
  transform: scale(1.15);
}
.sk-customer-chip.active {
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700));
  color: white;
  border-color: transparent;
  box-shadow: 0 3px 12px rgba(59, 130, 246, 0.35);
  transform: translateY(-1px);
}
.sk-customer-chip.active:hover {
  background: linear-gradient(135deg, var(--color-primary-600), var(--color-primary-800));
  box-shadow: 0 4px 16px rgba(59, 130, 246, 0.4);
}
.sk-customer-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-primary-500);
  font-size: 14px;
  flex-shrink: 0;
  padding: 0 4px;
}
.sk-bar-fade-enter-active {
  transition: opacity 0.2s ease;
}
.sk-bar-fade-leave-active {
  transition: opacity 0.15s ease;
}
.sk-bar-fade-enter-from,
.sk-bar-fade-leave-to {
  opacity: 0;
}
.sk-stat-row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-left: auto;
}
.sk-stat-card {
  border-radius: 10px;
  padding: 8px 14px;
  text-align: center;
  border: 1px solid transparent;
  transition: box-shadow 0.3s ease;
}
.sk-stat-card:hover {
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}
.sk-stat-value {
  font-size: 18px;
  font-weight: 800;
  margin-bottom: 1px;
  font-variant-numeric: tabular-nums;
}
.sk-stat-label {
  font-size: 11px;
  color: var(--color-text-secondary);
}
.sk-stat-primary { background: var(--color-primary-50); border-color: var(--color-primary-200); }
.sk-stat-primary .sk-stat-value { color: var(--color-primary-600); }
.sk-stat-warning { background: var(--color-warning-50); border-color: var(--color-warning-200); }
.sk-stat-warning .sk-stat-value { color: var(--color-warning-600); }
.sk-stat-success { background: var(--color-success-50); border-color: var(--color-success-200); }
.sk-stat-success .sk-stat-value { color: var(--color-success-600); }
.sk-stat-info { background: var(--color-info-50); border-color: var(--color-info-200); }
.sk-stat-info .sk-stat-value { color: var(--color-info-600); }
.sk-stat-stock { background: #f0fdf4; border-color: #bbf7d0; }
.sk-stat-stock .sk-stat-value { color: #16a34a; }
.sk-card-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
.sk-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.sk-table thead th {
  padding: 10px 14px;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  background: var(--color-surface, #f8fafc);
  border-bottom: 2px solid var(--color-border-light, #e2e8f0);
  color: var(--color-text-secondary);
  text-align: center;
  white-space: nowrap;
}
.sk-th-left { text-align: left !important; }
.sk-table tbody td {
  padding: 10px 14px;
  font-size: 13px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  text-align: center;
  vertical-align: middle;
  transition: background 0.2s ease;
  color: var(--color-text);
}
.sk-td-left { text-align: left !important; }
.sk-table tbody tr:hover {
  background: var(--color-primary-50);
}
.sk-customer-cell {
  display: flex;
  align-items: center;
  gap: 4px;
  font-weight: 600;
  white-space: nowrap;
}
.sk-customer-cell i {
  color: var(--color-primary-500);
  font-size: 12px;
}
.sk-product-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}
.sk-product-cell i {
  color: var(--color-text-secondary);
  font-size: 12px;
}
.sk-custom-orders {
  display: inline-grid;
  grid-template-columns: auto auto;
  text-align: left;
  line-height: 1.6;
  font-size: 12px;
}
.sk-custom-country {
  text-align: right;
  justify-self: end;
  color: var(--color-text-secondary);
}
.sk-available-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  align-items: center;
}
.sk-country-share {
  display: inline-grid;
  grid-template-columns: auto auto;
  text-align: left;
  line-height: 1.4;
  font-size: 12px;
  color: var(--color-text-secondary);
}
.sk-country-share-label {
  text-align: right;
  justify-self: end;
  margin-right: 4px;
}
.sk-text-negative { color: var(--color-danger-500); }
.sk-text-positive { color: var(--color-success-500); }
.sk-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-text-muted);
}
.sk-empty i { font-size: 28px; opacity: 0.5; }
.sk-empty span { font-size: 14px; }

/* Fetching progress bar */
.sk-fetching-bar {
  height: 2px;
  background: var(--color-primary-100, #e0f2fe);
  overflow: hidden;
  border-radius: 1px;
}
.sk-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500, #3b82f6);
  border-radius: 1px;
  animation: sk-progress-slide 1s ease-in-out infinite;
}
@keyframes sk-progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}

@media (max-width: 900px) {
  .sk-stat-row { flex-wrap: wrap; gap: 6px; }
  .sk-customer-bar-inner { padding: 8px 12px; gap: 8px; }
  .sk-customer-bar-label { display: none; }
  .sk-customer-chip { padding: 5px 12px; font-size: 11px; }
}
</style>
