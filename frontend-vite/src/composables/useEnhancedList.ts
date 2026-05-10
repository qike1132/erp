import { ref, computed, watch, readonly, onUnmounted } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { get } from '@/api/request'
import type { PaginatedResponse } from '@/types'

interface Options {
  key: string; url: string; perPage?: number; staleTime?: number
  prefetchPages?: number; debounceMs?: number; extraParams?: () => Record<string, any>
  enableKeyset?: boolean
}

export function useEnhancedList<T>(opts: Options) {
  const { key, url, perPage: defPP = 20, staleTime = 30_000, prefetchPages = 1, debounceMs = 300, extraParams, enableKeyset = false } = opts
  const qc = useQueryClient()
  const page = ref(1), perPage = ref(defPP), search = ref(''), dSearch = ref('')
  const sortBy = ref(''), sortOrder = ref<'asc'|'desc'>('desc'), total = ref(0)
  const keysetCursor = ref<string | number | undefined>(undefined)

  let timer: ReturnType<typeof setTimeout> | null = null
  watch(search, (v) => { if (timer) clearTimeout(timer); timer = setTimeout(() => { dSearch.value = v; page.value = 1; keysetCursor.value = undefined }, debounceMs) })
  onUnmounted(() => { if (timer) clearTimeout(timer) })

  const qk = computed(() => [key, page.value, perPage.value, dSearch.value, sortBy.value, sortOrder.value, keysetCursor.value, extraParams?.() ?? {}])
  const qp = computed(() => ({
    page: page.value, per_page: perPage.value, search: dSearch.value || undefined,
    sort_by: sortBy.value || undefined, sort_order: sortOrder.value || undefined,
    ...(enableKeyset && keysetCursor.value != null ? { keyset_cursor: keysetCursor.value } : {}),
    ...extraParams?.()
  }))

  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: qk,
    queryFn: async () => { const r = await get<PaginatedResponse<T>>(url, qp.value); total.value = r.total ?? 0; return r },
    staleTime,
    placeholderData: (prev) => prev,
  })

  watch([page, perPage, dSearch, sortBy, sortOrder], () => {
    if (enableKeyset && keysetCursor.value != null) return
    for (let i = 1; i <= prefetchPages; i++) {
      const np = page.value + i
      if (np * perPage.value < total.value + perPage.value) {
        qc.prefetchQuery({
          queryKey: [key, np, perPage.value, dSearch.value, sortBy.value, sortOrder.value, undefined, extraParams?.() ?? {}],
          queryFn: () => get<PaginatedResponse<T>>(url, { ...qp.value, page: np, keyset_cursor: undefined }),
          staleTime,
        })
      }
    }
  })

  const items = computed(() => data.value?.items ?? [])
  const totalPages = computed(() => data.value?.pages ?? Math.ceil(total.value / perPage.value))

  function handlePageChange(v: number) {
    page.value = v
    keysetCursor.value = undefined
  }

  return {
    page: readonly(page), perPage: readonly(perPage), search: readonly(search), dSearch: readonly(dSearch),
    sortBy: readonly(sortBy), sortOrder: readonly(sortOrder), items, total: readonly(total), totalPages,
    data, isLoading, isFetching, refetch,
    handlePageChange,
    handleSizeChange: (v: number) => { perPage.value = v; page.value = 1; keysetCursor.value = undefined },
    handleSort: (p: string, o: string|null) => { sortBy.value = p; sortOrder.value = o === 'ascending' ? 'asc' : 'desc'; page.value = 1; keysetCursor.value = undefined },
    handleSearch: (v: string) => { search.value = v },
    resetFilters: () => { search.value = ''; dSearch.value = ''; sortBy.value = ''; sortOrder.value = 'desc'; page.value = 1; keysetCursor.value = undefined },
  }
}
