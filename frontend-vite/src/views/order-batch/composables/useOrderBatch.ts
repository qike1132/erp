import { computed, ref } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { orderBatchApi } from '@/api'
import type { OrderBatchItem } from '@/types'

export function useOrderBatch() {
  const queryClient = useQueryClient()

  const page = ref(1)
  const perPage = ref(50)
  const batchNoFilter = ref('')
  const customerFilter = ref('')
  const statusFilter = ref('')
  const keywordSearch = ref('')

  const selectedIds = ref<number[]>([])
  const editingId = ref<number | null>(null)
  const editingValue = ref('')

  const filters = computed(() => ({
    page: page.value,
    per_page: perPage.value,
    batch_no: batchNoFilter.value || undefined,
    customer: customerFilter.value || undefined,
    status: statusFilter.value || undefined,
    keyword: keywordSearch.value || undefined,
  }))

  const { data, isLoading, refetch } = useQuery({
    queryKey: computed(() => ['order-batch', filters.value]),
    queryFn: () => orderBatchApi.orders(filters.value),
    staleTime: 10_000,
  })

  const orders = computed<OrderBatchItem[]>(() => data.value?.data ?? [])
  const total = computed(() => data.value?.total ?? 0)

  const { data: whitelistData } = useQuery({
    queryKey: ['order-batch-whitelist'],
    queryFn: () => orderBatchApi.whitelist(),
    staleTime: 300_000,
  })
  const whitelistCustomers = computed<string[]>(() => whitelistData.value?.customers ?? [])

  function toggleSelect(id: number) {
    const idx = selectedIds.value.indexOf(id)
    if (idx >= 0) selectedIds.value.splice(idx, 1)
    else selectedIds.value.push(id)
  }

  function toggleSelectAll() {
    if (selectedIds.value.length === orders.value.length) {
      selectedIds.value = []
    } else {
      selectedIds.value = orders.value.map(o => o.id)
    }
  }

  function startEdit(item: OrderBatchItem) {
    editingId.value = item.id
    editingValue.value = item.batch_no ?? ''
  }

  function cancelEdit() {
    editingId.value = null
    editingValue.value = ''
  }

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ['order-batch'] })
  }

  function handlePageChange(val: number) {
    page.value = val
  }

  return {
    page, perPage, batchNoFilter, customerFilter, statusFilter, keywordSearch,
    orders, total, isLoading, refetch,
    selectedIds, toggleSelect, toggleSelectAll,
    editingId, editingValue, startEdit, cancelEdit,
    whitelistCustomers,
    invalidate, handlePageChange,
  }
}
