import { computed, ref, watch } from 'vue'
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router'
import { useQuery } from '@tanstack/vue-query'
import { refDebounced } from '@vueuse/core'
import { get } from '@/api/request'
import type { PageResult } from '@/types'

/**
 * 通用列表查询 composable
 * - URL 参数同步（page, per_page, search, sort_by, sort_order）
 * - 自动 VueQuery useQuery
 * - search 防抖 300ms
 */
export function useListQuery<T>(key: string, url: string, extraParams?: () => Record<string, unknown>) {
  const route = useRoute()
  const router = useRouter()

  const page = ref(+(route.query.page || 1))
  const perPage = ref(+(route.query.per_page || 20))
  const search = ref((route.query.search as string) || '')
  const sortBy = ref((route.query.sort_by as string) || '')
  const sortOrder = ref((route.query.sort_order as string) || 'desc')

  const dSearch = refDebounced(search, 300)

  watch([page, perPage, dSearch, sortBy, sortOrder], () => {
    const query: LocationQueryRaw = { ...route.query }
    query.page = String(page.value)
    query.per_page = String(perPage.value)
    if (dSearch.value) query.search = dSearch.value
    else delete query.search
    if (sortBy.value) query.sort_by = sortBy.value
    if (sortOrder.value) query.sort_order = sortOrder.value
    router.replace({ query })
  })

  const queryKey = computed(() => [
    key,
    page.value,
    perPage.value,
    dSearch.value,
    sortBy.value,
    sortOrder.value,
    extraParams ? extraParams() : {},
  ])

  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey,
    queryFn: () =>
      get<PageResult<T>>(url, {
        page: page.value,
        per_page: perPage.value,
        search: dSearch.value || undefined,
        sort_by: sortBy.value || undefined,
        sort_order: sortOrder.value || undefined,
        ...extraParams?.(),
      }),
    staleTime: 30_000,
  })

  function handlePageChange(val: number) {
    page.value = val
  }

  function handleSizeChange(val: number) {
    perPage.value = val
    page.value = 1
  }

  function handleSort(prop: string, order: string | null) {
    sortBy.value = prop
    sortOrder.value = order === 'ascending' ? 'asc' : 'desc'
  }

  return {
    page,
    perPage,
    search,
    sortBy,
    sortOrder,
    data,
    isLoading,
    isFetching,
    refetch,
    handlePageChange,
    handleSizeChange,
    handleSort,
  }
}
