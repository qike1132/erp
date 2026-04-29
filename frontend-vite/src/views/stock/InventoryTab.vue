<template>
  <div class="sk-inventory">
    <!-- 筛选栏 -->
    <div class="sk-filter-bar">
      <div class="sk-filter-field">
        <label class="sk-filter-label">客户名称</label>
        <UiSelect v-model="filters.customer" placeholder="全部客户" :options="customerOptions" style="width: 200px" />
      </div>
      <div class="sk-filter-field">
        <label class="sk-filter-label">产品名称/69码</label>
        <input v-model="filters.product" class="sk-filter-input" placeholder="输入产品名称或69码" />
      </div>
      <div class="sk-filter-actions">
        <button class="sk-action-btn sk-action-primary" @click="handleSearch()">
          <i class="fas fa-search" style="margin-right: 4px" />查询
        </button>
        <button class="sk-action-btn sk-action-outline" @click="handleReset()">
          <i class="fas fa-redo" />
        </button>
      </div>
    </div>

    <!-- 定制国家标签 -->
    <div v-if="allCountries.length" class="sk-country-tags">
      <span class="sk-country-label">定制国家：</span>
      <span
        v-for="c in allCountries"
        :key="c"
        :class="['sk-country-tag', { active: filters.country === c }]"
        @click="toggleCountry(c)"
      >{{ c }}</span>
    </div>

    <!-- 统计卡片 -->
    <div v-if="filteredInventory.length" class="sk-stat-row">
      <div class="sk-stat-card sk-stat-primary">
        <div class="sk-stat-icon"><i class="fas fa-file-invoice" /></div>
        <div>
          <div class="sk-stat-value">{{ totalOrderQty }}</div>
          <div class="sk-stat-label">总订单数</div>
        </div>
      </div>
      <div class="sk-stat-card sk-stat-warning">
        <div class="sk-stat-icon"><i class="fas fa-globe" /></div>
        <div>
          <div class="sk-stat-value">{{ totalCustomQty }}</div>
          <div class="sk-stat-label">定制订单</div>
        </div>
      </div>
      <div class="sk-stat-card sk-stat-success">
        <div class="sk-stat-icon"><i class="fas fa-truck-loading" /></div>
        <div>
          <div class="sk-stat-value">{{ totalStockinQty }}</div>
          <div class="sk-stat-label">总备货数量</div>
        </div>
      </div>
      <div class="sk-stat-card sk-stat-info">
        <div class="sk-stat-icon"><i class="fas fa-boxes-stacked" /></div>
        <div>
          <div class="sk-stat-value">{{ totalStock }}</div>
          <div class="sk-stat-label">总库存</div>
        </div>
      </div>
    </div>

    <!-- 库存汇总表 -->
    <div class="sk-table-section">
      <div class="sk-section-header">
        <div class="sk-section-title">
          <i class="fas fa-cubes" style="color: var(--color-primary-500)" />
          库存汇总
        </div>
        <div class="sk-section-actions">
          <span class="sk-record-count">共 {{ filteredInventory.length }} 条记录</span>
          <button v-if="filteredInventory.length" class="sk-action-btn sk-action-success" @click="handleExport">
            <i class="fas fa-file-excel" style="margin-right: 4px" />导出
          </button>
        </div>
      </div>

      <div v-if="isLoading" class="sk-empty">
        <i class="fas fa-spinner fa-spin" />
        <span>加载中...</span>
      </div>
      <div v-else-if="filteredInventory.length === 0" class="sk-empty">
        <i class="fas fa-warehouse" />
        <span>暂无库存数据</span>
      </div>
      <table v-else class="sk-table">
        <thead>
          <tr>
            <th>客户</th>
            <th style="text-align: left">产品名称</th>
            <th>订单数量</th>
            <th>定制订单</th>
            <th>备货数量</th>
            <th>总库存</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in filteredInventory" :key="`${item.customer}-${item.product_name}`">
            <td>
              <span class="sk-customer-cell">
                <i class="fas fa-building" />
                {{ item.customer }}
              </span>
            </td>
            <td style="text-align: left">
              <span class="sk-product-cell">
                <i class="fas fa-cube" />
                <strong>{{ item.product_name }}</strong>
              </span>
            </td>
            <td>{{ item.order_quantity }}</td>
            <td>
              <div v-if="customOrderDetails(item).length" class="sk-custom-orders">
                <template v-for="d in customOrderDetails(item)" :key="d.country">
                  <span class="sk-custom-country">{{ d.country }}：</span><span>{{ d.qty }}</span>
                </template>
              </div>
            </td>
            <td>{{ item.stockin_quantity }}</td>
            <td>
              <strong :class="item.total_stock < 0 ? 'sk-text-negative' : 'sk-text-positive'">{{ item.total_stock }}</strong>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, computed } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { stockApi, customerApi } from '@/api'
import UiSelect from '@/components/ui/UiSelect.vue'

const filters = reactive({ customer: '', product: '', country: '' })

const { data: namesData } = useQuery({
  queryKey: ['customer-active-names'],
  queryFn: async () => {
    const res = (await customerApi.activeNames()) as any
    return res.names ?? res ?? []
  },
  staleTime: 30_000,
})
const customerNames = computed(() => {
  const arr = Array.isArray(namesData.value) ? namesData.value : []
  return arr.map((c: any) => c.name ?? c)
})
const customerOptions = computed(() => [
  { value: '', label: '全部客户' },
  ...customerNames.value.map((c: string) => ({ value: c, label: c })),
])

const {
  data: invData,
  isLoading,
  refetch,
} = useQuery({
  queryKey: ['inventory', filters],
  queryFn: () =>
    stockApi.inventory({
      customer: filters.customer || undefined,
      product: filters.product || undefined,
    }) as Promise<any>,
  staleTime: 30_000,
})

const inventory = computed(
  () =>
    invData.value?.data ??
    invData.value?.inventory ??
    invData.value?.items ??
    (Array.isArray(invData.value) ? invData.value : []),
)
const allCountries = computed(() => (invData.value?.all_countries ?? []) as string[])

const filteredInventory = computed(() => {
  if (!filters.country) return inventory.value
  return inventory.value.filter((item: any) => {
    const co = item.country_orders ?? {}
    return co[filters.country] && co[filters.country] !== 0
  })
})

function customOrderDetails(item: any): { country: string; qty: number }[] {
  const co = item.country_orders ?? {}
  const result: { country: string; qty: number }[] = []
  for (const [k, v] of Object.entries(co)) {
    if (k !== '常规' && v) result.push({ country: k, qty: Number(v) })
  }
  return result
}

const totalOrderQty = computed(
  () =>
    invData.value?.total_order_quantity ??
    filteredInventory.value.reduce((s: number, i: any) => s + (Number(i.order_quantity) || 0), 0),
)
const totalCustomQty = computed(() =>
  filteredInventory.value.reduce((s: number, i: any) => s + customOrderDetails(i).reduce((ss: number, d: any) => ss + d.qty, 0), 0),
)
const totalStockinQty = computed(
  () =>
    invData.value?.total_stockin_quantity ??
    filteredInventory.value.reduce((s: number, i: any) => s + (Number(i.stockin_quantity) || 0), 0),
)
const totalStock = computed(
  () =>
    invData.value?.total_stock ?? filteredInventory.value.reduce((s: number, i: any) => s + (Number(i.total_stock) || 0), 0),
)

function toggleCountry(c: string) {
  filters.country = filters.country === c ? '' : c
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
async function handleExport() {
  try {
    await stockApi.exportInventory({ customer: filters.customer, product: filters.product })
  } catch (_e) {
    /* error handled by interceptor */
  }
}
</script>

<style scoped>
.sk-inventory {
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* Filter Bar */
.sk-filter-bar {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: flex-end;
  padding-bottom: 12px;
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
  transition: all 0.3s ease;
  font-family: inherit;
  color: var(--color-text);
  background: white;
}
.sk-filter-input:focus {
  border-color: var(--color-primary-400);
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.sk-filter-actions {
  display: flex;
  gap: 8px;
  align-items: flex-end;
}

/* Action Buttons */
.sk-action-btn {
  padding: 7px 14px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  background: white;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
  color: var(--color-text-secondary);
  display: inline-flex;
  align-items: center;
}
.sk-action-primary { color: var(--color-primary-600); }
.sk-action-primary:hover { background: var(--color-primary-50); border-color: var(--color-primary-300); transform: translateY(-1px); }
.sk-action-outline { }
.sk-action-success { color: var(--color-success-600); border-color: var(--color-success-200); }
.sk-action-success:hover { background: var(--color-success-50); border-color: var(--color-success-300); transform: translateY(-1px); }

/* Country Tags */
.sk-country-tags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}
.sk-country-label {
  font-size: 13px;
  color: var(--color-text-secondary);
  white-space: nowrap;
}
.sk-country-tag {
  display: inline-flex;
  align-items: center;
  padding: 5px 14px;
  border-radius: 16px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  border: 2px solid var(--color-border-light, #e2e8f0);
  background: white;
  color: var(--color-text-secondary);
  transition: all 0.3s ease;
  user-select: none;
}
.sk-country-tag:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-600);
}
.sk-country-tag.active {
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700));
  color: white;
  border-color: transparent;
  box-shadow: 0 2px 8px rgba(91, 141, 239, 0.3);
}

/* Stat Cards */
.sk-stat-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}
.sk-stat-card {
  border-radius: 11px;
  padding: 12px 14px;
  border: 1px solid transparent;
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  display: flex;
  align-items: center;
  gap: 10px;
}
.sk-stat-card:hover {
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
  transform: translateY(-1px);
}
.sk-stat-icon {
  width: 36px;
  height: 36px;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  flex-shrink: 0;
}
.sk-stat-value {
  font-size: 20px;
  font-weight: 700;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}
.sk-stat-label {
  font-size: 11px;
  color: var(--color-text-secondary);
  margin-top: 1px;
}
.sk-stat-primary {
  background: var(--color-primary-50);
  border-color: var(--color-primary-200);
}
.sk-stat-primary .sk-stat-icon { background: var(--color-primary-100); color: var(--color-primary-600); }
.sk-stat-primary .sk-stat-value { color: var(--color-primary-600); }
.sk-stat-warning {
  background: var(--color-warning-50);
  border-color: var(--color-warning-200);
}
.sk-stat-warning .sk-stat-icon { background: var(--color-warning-100); color: var(--color-warning-600); }
.sk-stat-warning .sk-stat-value { color: var(--color-warning-600); }
.sk-stat-success {
  background: var(--color-success-50);
  border-color: var(--color-success-200);
}
.sk-stat-success .sk-stat-icon { background: var(--color-success-100); color: var(--color-success-600); }
.sk-stat-success .sk-stat-value { color: var(--color-success-600); }
.sk-stat-info {
  background: var(--color-info-50);
  border-color: var(--color-info-200);
}
.sk-stat-info .sk-stat-icon { background: var(--color-info-100); color: var(--color-info-600); }
.sk-stat-info .sk-stat-value { color: var(--color-info-600); }

/* Table Section */
.sk-table-section {
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 13px;
  overflow: hidden;
  background: white;
}
.sk-section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
}
.sk-section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
}
.sk-section-title i { font-size: 14px; }
.sk-section-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.sk-record-count {
  font-size: 13px;
  color: var(--color-text-muted);
}

/* Table */
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
.sk-table tbody td {
  padding: 10px 14px;
  font-size: 13px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  text-align: center;
  vertical-align: middle;
  transition: background 0.2s ease;
  color: var(--color-text);
}
.sk-table tbody tr:hover {
  background: var(--color-primary-50);
}

/* Customer Cell */
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

/* Product Cell */
.sk-product-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}
.sk-product-cell i {
  color: var(--color-text-secondary);
  font-size: 12px;
}

/* Custom Orders */
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

/* Text Colors */
.sk-text-negative { color: var(--color-danger-500); }
.sk-text-positive { color: var(--color-success-500); }

/* Empty */
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

/* Responsive */
@media (max-width: 900px) {
  .sk-stat-row { grid-template-columns: repeat(2, 1fr); gap: 8px; }
}
</style>
