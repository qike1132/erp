<template>
  <div class="ob-container">
    <div class="ob-card">
      <div class="ob-header">
        <h2 class="ob-title">批次历史记录</h2>
        <button class="ob-btn ob-btn--outline" @click="$emit('close')">返回</button>
      </div>

      <div class="ob-filters">
        <input v-model="batchNoFilter" class="ob-input" placeholder="批次号筛选" name="search" autocomplete="off" @input="debouncedLoadHistory" />
        <select v-model="customerFilter" class="ob-select" @change="loadHistory">
          <option value="">全部客户</option>
          <option v-for="c in whitelist" :key="c" :value="c">{{ c }}</option>
        </select>
        <input v-model="dateFrom" type="date" class="ob-input" name="date" autocomplete="off" @change="loadHistory" />
        <span class="ob-filter-sep">至</span>
        <input v-model="dateTo" type="date" class="ob-input" name="date" autocomplete="off" @change="loadHistory" />
      </div>

      <div v-if="loading" class="ob-loading">加载中…</div>
      <div v-else-if="orders.length === 0" class="ob-empty">暂无历史记录</div>

      <template v-else>
        <div class="ob-table-wrap">
          <table class="ob-table">
            <thead>
              <tr>
                <th class="ob-th">批次号</th>
                <th class="ob-th">订单编号</th>
                <th class="ob-th">客户</th>
                <th class="ob-th">产品</th>
                <th class="ob-th">数量</th>
                <th class="ob-th">归档完成时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="order in orders" :key="order.id" class="ob-tr">
                <td class="ob-td">{{ order.batch_no }}</td>
                <td class="ob-td">{{ order.order_no }}</td>
                <td class="ob-td">{{ order.customer }}</td>
                <td class="ob-td">{{ order.product_name }}</td>
                <td class="ob-td">{{ order.quantity }}</td>
                <td class="ob-td">{{ formatDate(order.batch_completed_at) }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="ob-pagination">
          <button class="ob-btn ob-btn--ghost ob-btn--sm" :disabled="page <= 1" @click="changePage(page - 1)">上一页</button>
          <span class="ob-page-info">{{ page }} / {{ totalPages }}</span>
          <button class="ob-btn ob-btn--ghost ob-btn--sm" :disabled="page >= totalPages" @click="changePage(page + 1)">下一页</button>
          <span class="ob-total-info">共 {{ total }} 条</span>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onScopeDispose, ref } from 'vue'
import { orderBatchApi } from '@/api'
import type { OrderBatchItem } from '@/types'
import { formatDate } from '@/utils/format'

defineEmits<{ close: [] }>()

const orders = ref<OrderBatchItem[]>([])
const total = ref(0)
const page = ref(1)
const perPage = ref(50)
const loading = ref(false)
const whitelist = ref<string[]>([])

const batchNoFilter = ref('')
const customerFilter = ref('')
const dateFrom = ref('')
const dateTo = ref('')

let _debTimer: ReturnType<typeof setTimeout> | null = null
function debouncedLoadHistory() {
  if (_debTimer) clearTimeout(_debTimer)
  if (!batchNoFilter.value) { loadHistory(); return }
  _debTimer = setTimeout(loadHistory, 300)
}
onScopeDispose(() => {
  if (_debTimer) clearTimeout(_debTimer)
})

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / perPage.value)))

async function loadHistory() {
  loading.value = true
  try {
    const res = await orderBatchApi.history({
      page: page.value,
      per_page: perPage.value,
      batch_no: batchNoFilter.value || undefined,
      customer: customerFilter.value || undefined,
      date_from: dateFrom.value || undefined,
      date_to: dateTo.value || undefined,
    } as any)
    orders.value = res.data ?? []
    total.value = res.total ?? 0
  } finally {
    loading.value = false
  }
}

function changePage(p: number) {
  page.value = p
  loadHistory()
}

onMounted(async () => {
  const wl = await orderBatchApi.whitelist()
  whitelist.value = wl.customers ?? []
  loadHistory()
})
</script>

<style scoped>
.ob-container { min-height: 100vh; background: #F5F5F5; padding: 20px; }
.ob-card { background: #FFFFFF; border-radius: 12px; border: 1px solid #E5E7EB; padding: 24px; }
.ob-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.ob-title { font-size: 20px; font-weight: 700; color: #1F2937; margin: 0; }
.ob-filters { display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; align-items: center; }
.ob-filter-sep { color: #9CA3AF; font-size: 14px; }
.ob-input { padding: 8px 12px; border: 1px solid #D1D5DB; border-radius: 8px; font-size: 14px; background: #FFFFFF; min-width: 140px; }
.ob-select { padding: 8px 12px; border: 1px solid #D1D5DB; border-radius: 8px; font-size: 14px; background: #FFFFFF; min-width: 140px; }
.ob-btn { padding: 8px 16px; border-radius: 8px; font-size: 14px; cursor: pointer; border: 1px solid transparent; }
.ob-btn--outline { background: #FFFFFF; color: #374151; border-color: #D1D5DB; }
.ob-btn--ghost { background: transparent; color: #6B7280; }
.ob-btn--ghost:disabled { color: #D1D5DB; cursor: not-allowed; }
.ob-btn--sm { padding: 4px 10px; font-size: 13px; }
.ob-loading, .ob-empty { text-align: center; padding: 40px; color: #9CA3AF; font-size: 14px; }
.ob-table-wrap { overflow-x: auto; }
.ob-table { width: 100%; border-collapse: collapse; font-size: 14px; }
.ob-th { padding: 10px 12px; text-align: left; font-weight: 600; color: #6B7280; border-bottom: 2px solid #E5E7EB; }
.ob-td { padding: 10px 12px; border-bottom: 1px solid #F3F4F6; color: #374151; }
.ob-tr:hover { background: #F9FAFB; }
.ob-pagination { display: flex; align-items: center; justify-content: center; gap: 12px; padding: 16px 0; }
.ob-page-info { font-size: 14px; color: #374151; }
.ob-total-info { font-size: 13px; color: #9CA3AF; }
</style>
