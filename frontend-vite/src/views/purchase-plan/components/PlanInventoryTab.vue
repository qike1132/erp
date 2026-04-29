<template>
  <div class="inv-tab">
    <div v-if="isLoading" class="inv-state"><UiSpinner /> 加载中...</div>
    <div v-else-if="isError" class="inv-state">
      <i class="fas fa-exclamation-circle" style="color:var(--color-danger-500)" /> 加载失败
      <a href="#" @click.prevent="refetch" style="color:var(--color-primary-500);margin-left:4px">重试</a>
    </div>
    <UiEmpty v-else-if="!hasData" description="暂无库存对比数据" />

    <template v-else>
      <div class="inv-summary">
        <div class="inv-summary-card inv-sufficient">
          <div class="inv-s-icon"><i class="fas fa-check-circle" /></div>
          <div class="inv-s-body">
            <span class="inv-s-val">{{ sufficientCount }}</span>
            <span class="inv-s-lbl">库存充足</span>
          </div>
        </div>
        <div class="inv-summary-card inv-shortage">
          <div class="inv-s-icon"><i class="fas fa-exclamation-triangle" /></div>
          <div class="inv-s-body">
            <span class="inv-s-val">{{ shortageCount }}</span>
            <span class="inv-s-lbl">库存不足</span>
          </div>
        </div>
        <div class="inv-summary-card inv-total">
          <div class="inv-s-icon"><i class="fas fa-boxes-stacked" /></div>
          <div class="inv-s-body">
            <span class="inv-s-val">{{ totalPlanQty }}</span>
            <span class="inv-s-lbl">计划总量</span>
          </div>
        </div>
        <div class="inv-summary-card inv-inventory">
          <div class="inv-s-icon"><i class="fas fa-warehouse" /></div>
          <div class="inv-s-body">
            <span class="inv-s-val">{{ totalInventoryQty }}</span>
            <span class="inv-s-lbl">库存总量</span>
          </div>
        </div>
      </div>

      <div class="inv-table-card">
        <table class="inv-table">
          <thead>
            <tr>
              <th>客户名称</th>
              <th>产品名称</th>
              <th>条码</th>
              <th class="inv-th-num">计划数量</th>
              <th class="inv-th-num">库存数量</th>
              <th class="inv-th-num">差额</th>
              <th class="inv-th-status">库存状态</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in inventoryList"
              :key="row.detail_id"
              :class="{ 'inv-row-shortage': row.diff < 0 }"
            >
              <td class="inv-td-customer">{{ row.customer_name }}</td>
              <td class="inv-td-product">{{ row.product_name }}</td>
              <td class="inv-td-barcode">{{ row.barcode }}</td>
              <td class="inv-td-num"><b>{{ row.plan_qty }}</b></td>
              <td class="inv-td-num">{{ row.inventory_qty }}</td>
              <td class="inv-td-num">
                <span :class="row.diff < 0 ? 'inv-c-danger' : row.diff > 0 ? 'inv-c-success' : 'inv-c-muted'">
                  {{ row.diff > 0 ? '+' : '' }}{{ row.diff }}
                </span>
              </td>
              <td class="inv-td-status">
                <span class="inv-status" :class="stockStatusCls(row.stock_status)">
                  {{ stockStatusTxt(row.stock_status, row.diff) }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { planApi } from '@/api'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'

const props = defineProps<{
  year: number
  month: number
  customerId: string
}>()

const { data: inventoryData, isLoading, isError, refetch } = useQuery({
  queryKey: ['plan-inventory-compare', () => props.year, () => props.month, () => props.customerId],
  queryFn: async () => {
    const p: any = { year: props.year, month: props.month }
    if (props.customerId) p.customer_id = Number(props.customerId)
    return (await planApi.inventoryCompare(p)) as any
  },
  staleTime: 30_000,
})

const inventoryList = computed(() => inventoryData.value?.details ?? [])
const hasData = computed(() => inventoryList.value.length > 0)

const sufficientCount = computed(() => inventoryList.value.filter((r: any) => r.diff >= 0).length)
const shortageCount = computed(() => inventoryList.value.filter((r: any) => r.diff < 0).length)
const totalPlanQty = computed(() => inventoryList.value.reduce((s: number, r: any) => s + Number(r.plan_qty || 0), 0))
const totalInventoryQty = computed(() => inventoryList.value.reduce((s: number, r: any) => s + Number(r.inventory_qty || 0), 0))

function stockStatusCls(s: string) {
  if (s === 'shortage') return 'inv-st-shortage'
  if (s === 'warning') return 'inv-st-warning'
  return 'inv-st-sufficient'
}
function stockStatusTxt(s: string, diff: number) {
  if (s === 'shortage' || diff < 0) return '库存不足'
  if (s === 'warning') return '库存偏低'
  return '库存充足'
}
</script>

<style scoped>
.inv-tab { display: flex; flex-direction: column; gap: 16px; }
.inv-state {
  display: flex; align-items: center; justify-content: center;
  padding: 48px 0; color: var(--color-text-muted); gap: 8px;
}

.inv-summary {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.inv-summary-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  background: var(--color-surface-card);
  border-radius: var(--radius-card);
  border: 1px solid var(--color-border-light);
  box-shadow: var(--shadow-sm);
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}
.inv-summary-card:hover {
  transform: translateY(-6px);
  box-shadow: 0 12px 36px rgba(0,0,0,0.08), 0 48px 144px rgba(0,0,0,0.12);
}
.inv-s-icon {
  width: 42px; height: 42px;
  border-radius: var(--radius-md);
  display: flex; align-items: center; justify-content: center;
  font-size: 1rem;
}
.inv-s-body { display: flex; flex-direction: column; gap: 2px; }
.inv-s-val { font-size: 1.35rem; font-weight: 900; line-height: 1; }
.inv-s-lbl { font-size: 0.7rem; font-weight: 600; color: var(--color-text-secondary); }

.inv-sufficient .inv-s-icon { background: var(--color-success-50); color: var(--color-success-500); }
.inv-sufficient .inv-s-val { color: var(--color-success-500); }
.inv-shortage .inv-s-icon { background: var(--color-danger-50); color: var(--color-danger-500); }
.inv-shortage .inv-s-val { color: var(--color-danger-500); }
.inv-total .inv-s-icon { background: var(--color-primary-50); color: var(--color-primary-500); }
.inv-total .inv-s-val { color: var(--color-primary-500); }
.inv-inventory .inv-s-icon { background: var(--color-ocean-light); color: var(--color-ocean-text); }
.inv-inventory .inv-s-val { color: var(--color-heading); }

.inv-table-card {
  background: var(--color-surface-card);
  border-radius: var(--radius-card);
  border: 1px solid var(--color-border-light);
  box-shadow: var(--shadow-sm);
  overflow-x: auto;
}
.inv-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.82rem;
  min-width: 640px;
}
.inv-table thead th {
  padding: 12px 14px;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.5px;
  color: var(--color-text-secondary);
  background: var(--gradient-card-header);
  border-bottom: 2px solid var(--color-border-light);
  text-align: left;
  white-space: nowrap;
  position: sticky;
  top: 0;
  z-index: 1;
}
.inv-th-num, .inv-th-status { text-align: center; }

.inv-table tbody td {
  padding: 10px 14px;
  border-bottom: 1px solid var(--color-border-light);
}
.inv-table tbody tr:hover {
  background: rgba(91, 141, 239, 0.03);
}
.inv-row-shortage {
  background: rgba(234, 84, 85, 0.03);
}
.inv-row-shortage:hover {
  background: rgba(234, 84, 85, 0.06) !important;
}

.inv-td-customer { font-weight: 700; color: var(--color-text); }
.inv-td-product {
  color: var(--color-text);
  max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.inv-td-barcode {
  font-family: var(--font-mono); font-size: 0.72rem;
  color: var(--color-text-muted);
}
.inv-td-num { text-align: center; }
.inv-td-num b { font-weight: 800; color: var(--color-text); }

.inv-c-success { color: var(--color-success-500); font-weight: 600; }
.inv-c-danger { color: var(--color-danger-500); font-weight: 600; }
.inv-c-muted { color: var(--color-text-muted); }

.inv-td-status { text-align: center; }
.inv-status {
  display: inline-block; padding: 3px 12px;
  border-radius: 6px; font-size: 0.7rem; font-weight: 600;
}
.inv-st-sufficient { background: var(--color-success-50); color: var(--color-success-600); }
.inv-st-warning { background: var(--color-warning-50); color: var(--color-warning-600); }
.inv-st-shortage { background: var(--color-danger-50); color: var(--color-danger-600); }

@media (max-width: 1024px) {
  .inv-summary { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 640px) {
  .inv-summary { grid-template-columns: 1fr 1fr; }
}
</style>
