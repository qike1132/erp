<template>
  <div class="batch-page">
    <UiPageHeader>批次管理<template #description>查看和管理产品批次信息</template></UiPageHeader>

    <UiCard>
      <div style="display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap">
        <UiInput v-model="filters.batch_no" placeholder="批次号" style="width: 160px" />
        <UiInput v-model="filters.sku" placeholder="SKU编号" style="width: 160px" />
        <UiSelect v-model="filters.status" placeholder="状态" style="width: 120px" :options="statusOptions" />
        <UiDatePicker v-model="filters.startDate" style="width: 130px" />
        <span style="line-height: 36px; color: var(--color-text-muted)">-</span>
        <UiDatePicker v-model="filters.endDate" style="width: 130px" />
        <UiButton variant="primary" @click="refetch()"> 查询 </UiButton>
        <UiButton variant="outline" @click="exportData"> 导出 CSV </UiButton>
      </div>

      <div v-if="isLoading" class="flex justify-center py-12">
        <UiSpinner />
      </div>
      <UiTable v-else>
        <template #header>
          <th
            class="px-4 py-3 text-left text-xs font-semibold text-text-secondary uppercase tracking-wider cursor-pointer hover:text-primary-500"
            style="width: 160px"
            @click="
              handleSort({ prop: 'sku', order: sortBy === 'sku' && sortOrder === 'asc' ? 'ascending' : 'descending' })
            "
          >
            SKU编号
            <i
              v-if="sortBy === 'sku'"
              :class="sortOrder === 'asc' ? 'fas fa-sort-up' : 'fas fa-sort-down'"
              class="ml-1"
            />
          </th>
          <th
            class="px-4 py-3 text-left text-xs font-semibold text-text-secondary uppercase tracking-wider cursor-pointer hover:text-primary-500"
            style="width: 160px"
            @click="
              handleSort({
                prop: 'batch_no',
                order: sortBy === 'batch_no' && sortOrder === 'asc' ? 'ascending' : 'descending',
              })
            "
          >
            批次号
            <i
              v-if="sortBy === 'batch_no'"
              :class="sortOrder === 'asc' ? 'fas fa-sort-up' : 'fas fa-sort-down'"
              class="ml-1"
            />
          </th>
          <th
            class="px-4 py-3 text-left text-xs font-semibold text-text-secondary uppercase tracking-wider"
            style="min-width: 150px"
          >
            产品名称
          </th>
          <th
            class="px-4 py-3 text-right text-xs font-semibold text-text-secondary uppercase tracking-wider"
            style="width: 100px"
          >
            数量
          </th>
          <th
            class="px-4 py-3 text-left text-xs font-semibold text-text-secondary uppercase tracking-wider"
            style="width: 100px"
          >
            状态
          </th>
          <th
            class="px-4 py-3 text-left text-xs font-semibold text-text-secondary uppercase tracking-wider cursor-pointer hover:text-primary-500"
            style="width: 120px"
            @click="
              handleSort({
                prop: 'production_date',
                order: sortBy === 'production_date' && sortOrder === 'asc' ? 'ascending' : 'descending',
              })
            "
          >
            生产日期
            <i
              v-if="sortBy === 'production_date'"
              :class="sortOrder === 'asc' ? 'fas fa-sort-up' : 'fas fa-sort-down'"
              class="ml-1"
            />
          </th>
          <th
            class="px-4 py-3 text-left text-xs font-semibold text-text-secondary uppercase tracking-wider"
            style="width: 120px"
          >
            有效期
          </th>
        </template>
        <tr
          v-for="row in items"
          :key="row.id ?? row.batch_no"
          class="border-b border-border-light hover:bg-surface transition-colors"
        >
          <td class="px-4 py-3 text-sm">
            {{ row.sku }}
          </td>
          <td class="px-4 py-3 text-sm">
            {{ row.batch_no }}
          </td>
          <td class="px-4 py-3 text-sm">
            {{ row.product_name }}
          </td>
          <td class="px-4 py-3 text-sm text-right">
            {{ row.quantity }}
          </td>
          <td class="px-4 py-3 text-sm">
            <UiBadge
              :variant="row.status === 'completed' ? 'completed' : row.status === 'discontinued' ? 'info' : 'pending'"
            >
              {{ row.status === 'completed' ? '完成' : row.status === 'discontinued' ? '停用' : '在产' }}
            </UiBadge>
          </td>
          <td class="px-4 py-3 text-sm">
            {{ row.production_date }}
          </td>
          <td class="px-4 py-3 text-sm">
            {{ row.expiry_date }}
          </td>
        </tr>
        <template v-if="!items.length">
          <tr>
            <td colspan="7">
              <UiEmpty text="暂无批次数据" />
            </td>
          </tr>
        </template>
      </UiTable>

      <div style="display: flex; justify-content: flex-end; margin-top: 16px">
        <UiPagination :current-page="page" :total-pages="totalPages" @update:current-page="handlePageChange" />
      </div>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { batchApi } from '@/api'
import UiCard from '@/components/ui/UiCard.vue'
import UiInput from '@/components/ui/UiInput.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
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
const sortBy = ref('')
const sortOrder = ref('desc')

const filters = reactive({ batch_no: '', sku: '', status: '', startDate: '', endDate: '' })

const statusOptions = [
  { value: '', label: '全部' },
  { value: 'in_production', label: '在产' },
  { value: 'completed', label: '完成' },
  { value: 'discontinued', label: '停用' },
]

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / perPage.value)))

const {
  data: result,
  isLoading,
  refetch,
} = useQuery({
  queryKey: ['batch-list', page, perPage, sortBy, sortOrder, filters],
  queryFn: async () => {
    const params: Record<string, any> = { page: page.value, per_page: perPage.value }
    if (filters.batch_no) params.batch_no = filters.batch_no
    if (filters.sku) params.sku = filters.sku
    if (filters.status) params.status = filters.status
    if (sortBy.value) {
      params.sort_by = sortBy.value
      params.sort_order = sortOrder.value
    }
    const res = (await batchApi.list(params)) as any
    total.value = res.total ?? 0
    return res
  },
  staleTime: 30_000,
})

const items = computed(() => result.value?.items ?? result.value?.data ?? [])

function handleSort({ prop, order }: any) {
  sortBy.value = prop || ''
  sortOrder.value = order === 'ascending' ? 'asc' : 'desc'
}

function handlePageChange(p: number) {
  page.value = p
  refetch()
}

function exportData() {
  if (!items.value.length) {
    showToast('无数据可导出', 'warning')
    return
  }
  const headers = ['SKU编号', '批次号', '产品名称', '数量', '状态', '生产日期', '有效期']
  let csv = '\uFEFF' + headers.join(',') + '\n'
  items.value.forEach((r: any) => {
    csv +=
      [r.sku, r.batch_no, r.product_name, r.quantity, r.status, r.production_date, r.expiry_date]
        .map((c) => `"${String(c ?? '').replace(/"/g, '""')}"`)
        .join(',') + '\n'
  })
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `批次管理_${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
}
</script>
