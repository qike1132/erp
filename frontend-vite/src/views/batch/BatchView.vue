<template>
  <div class="batch-page">
    <UiPageHeader>批次号查询<template #description>按客户订单查询批次号及备货状态，仅显示白名单客户（MINISO）订单</template></UiPageHeader>

    <UiCard>
      <div class="bt-filterbar">
        <UiInput v-model="filters.batch_no" placeholder="批次号" style="width: 140px" />
        <UiInput v-model="filters.customer" placeholder="客户名称" style="width: 150px" />
        <UiSelect v-model="filters.status" placeholder="状态" style="width: 120px" :options="statusOptions" />
        <UiInput v-model="filters.keyword" placeholder="订单号搜索" style="width: 160px" />
        <UiButton variant="primary" @click="refetch()"> 查询 </UiButton>
        <UiButton variant="outline" @click="exportData"> 导出 CSV </UiButton>
      </div>

      <div v-if="isLoading && !result" class="flex justify-center py-12">
        <UiSpinner />
      </div>
      <template v-else>
      <div v-if="isFetching" class="bt-fetching-bar"><div class="bt-fetching-progress" /></div>
      <UiTable>
        <template #header>
          <th class="px-4 py-3 text-left text-xs font-semibold text-text-secondary uppercase tracking-wider" style="width: 150px">
            订单号
          </th>
          <th class="px-4 py-3 text-left text-xs font-semibold text-text-secondary uppercase tracking-wider" style="width: 120px">
            客户
          </th>
          <th class="px-4 py-3 text-left text-xs font-semibold text-text-secondary uppercase tracking-wider" style="min-width: 130px">
            产品名称
          </th>
          <th class="px-4 py-3 text-left text-xs font-semibold text-text-secondary uppercase tracking-wider" style="width: 120px">
            SKU条码
          </th>
          <th class="px-4 py-3 text-right text-xs font-semibold text-text-secondary uppercase tracking-wider" style="width: 80px">
            订单数量
          </th>
          <th class="px-4 py-3 text-right text-xs font-semibold text-text-secondary uppercase tracking-wider" style="width: 80px">
            备货数量
          </th>
          <th class="px-4 py-3 text-right text-xs font-semibold text-text-secondary uppercase tracking-wider" style="width: 80px">
            出货数量
          </th>
          <th class="px-4 py-3 text-left text-xs font-semibold text-text-secondary uppercase tracking-wider" style="width: 90px">
            状态
          </th>
          <th class="px-4 py-3 text-left text-xs font-semibold text-text-secondary uppercase tracking-wider" style="width: 130px">
            批次号
          </th>
        </template>
        <tr
          v-for="row in items"
          :key="row.id"
          class="border-b border-border-light hover:bg-surface transition-colors"
        >
          <td class="px-4 py-3 text-sm font-mono">
            {{ row.order_no }}
          </td>
          <td class="px-4 py-3 text-sm">
            {{ row.customer }}
          </td>
          <td class="px-4 py-3 text-sm">
            {{ row.product_name ?? '-' }}
          </td>
          <td class="px-4 py-3 text-sm font-mono">
            {{ row.product_barcode ?? '-' }}
          </td>
          <td class="px-4 py-3 text-sm text-right">
            {{ row.quantity }}
          </td>
          <td class="px-4 py-3 text-sm text-right">
            <span :class="row.deducted_qty >= row.quantity ? 'text-green-600 font-medium' : row.deducted_qty > 0 ? 'text-amber-600' : 'text-text-muted'">
              {{ row.deducted_qty }}
            </span>
          </td>
          <td class="px-4 py-3 text-sm text-right">
            <span :class="row.shipped_qty > 0 ? 'text-blue-600 font-medium' : 'text-text-muted'">
              {{ row.shipped_qty }}
            </span>
          </td>
          <td class="px-4 py-3 text-sm">
            <UiBadge :variant="statusVariant(row.status)">
              {{ statusLabel(row.status) }}
            </UiBadge>
          </td>
          <td class="px-4 py-3 text-sm font-mono">
            {{ row.batch_no ?? '-' }}
          </td>
        </tr>
        <template v-if="!items.length">
          <tr>
            <td colspan="9">
              <UiEmpty text="暂无批次数据" />
            </td>
          </tr>
        </template>
      </UiTable>
      </template>

      <UiPagination :current-page="page" :total-pages="totalPages" @update:current-page="handlePageChange" />
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { useQuery, keepPreviousData } from '@tanstack/vue-query'
import { batchApi } from '@/api'
import type { BatchQueryItem } from '@/types'
import UiCard from '@/components/ui/UiCard.vue'
import UiInput from '@/components/ui/UiInput.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiTable from '@/components/ui/UiTable.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'

import { showToast } from '@/composables/useToast'

const page = ref(1)
const perPage = ref(20)
const total = ref(0)

const filters = reactive({ batch_no: '', customer: '', status: '', keyword: '' })

const statusOptions = [
  { value: '', label: '全部' },
  { value: '待备货', label: '待备货' },
  { value: '部分备货', label: '部分备货' },
  { value: '已备货', label: '已备货' },
  { value: '待出货', label: '待出货' },
  { value: '已出货', label: '已出货' },
  { value: '批次已完成', label: '批次已完成' },
]

const statusVariant = (s: string | null): string => {
  if (!s) return 'default'
  if (s === '已出货' || s === '批次已完成') return 'completed'
  if (s === '待备货') return 'pending'
  if (s === '部分备货' || s === '待出货') return 'warning'
  if (s === '已备货') return 'info'
  return 'default'
}

const statusLabel = (s: string | null): string => s ?? '-'

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / perPage.value)))

const {
  data: result,
  isLoading,
  isFetching,
  refetch,
} = useQuery({
  queryKey: ['batch-query', page, perPage, filters],
  queryFn: async () => {
    const params: Record<string, unknown> = { page: page.value, per_page: perPage.value }
    if (filters.batch_no) params.batch_no = filters.batch_no
    if (filters.customer) params.customer = filters.customer
    if (filters.status) params.status = filters.status
    if (filters.keyword) params.keyword = filters.keyword
    const res = await batchApi.list(params)
    total.value = (res as any).total ?? 0
    return res
  },
  staleTime: 30_000,
  placeholderData: keepPreviousData,
})

const items = computed<BatchQueryItem[]>(() => (result.value as any)?.data ?? [])

function handlePageChange(p: number) {
  page.value = p
  refetch()
}

function exportData() {
  if (!items.value.length) {
    showToast('无数据可导出', 'warning')
    return
  }
  const headers = ['订单号', '客户', '产品名称', 'SKU条码', '订单数量', '备货数量', '出货数量', '状态', '批次号']
  let csv = '\uFEFF' + headers.join(',') + '\n'
  items.value.forEach((r) => {
    csv +=
      [r.order_no, r.customer, r.product_name ?? '', r.product_barcode ?? '', r.quantity, r.deducted_qty, r.shipped_qty, r.status ?? '', r.batch_no ?? '']
        .map((c) => {
          let s = String(c).replace(/"/g, '""')
          if (/^[=+\-@\t\r]/.test(s)) s = "'" + s
          return `"${s}"`
        })
        .join(',') + '\n'
  })
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `批次号查询_${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(link.href)
}
</script>

<style scoped>
.bt-filterbar {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
  flex-wrap: wrap;
  align-items: center;
}

.bt-fetching-bar {
  height: 2px;
  background: var(--color-primary-100, #e0f2fe);
  overflow: hidden;
  border-radius: 1px;
  margin-bottom: 8px;
}

.bt-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500, #3b82f6);
  border-radius: 1px;
  animation: bt-progress-slide 1s ease-in-out infinite;
}

@keyframes bt-progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}
</style>