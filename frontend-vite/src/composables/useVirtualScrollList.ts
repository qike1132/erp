import { ref, computed, watch, readonly } from 'vue'
import { useInfiniteQuery } from '@tanstack/vue-query'
import { get } from '@/api/request'
import type { PaginatedResponse } from '@/types'

/**
 * 虚拟滚动 + 无限加载 composable
 *
 * 适用场景：数据量超过 20,000 条的列表页，需要虚拟滚动 + 无限加载替代传统分页
 *
 * 设计：
 * - 使用 useInfiniteQuery 实现无限滚动，每次加载 perPage 条
 * - 所有已加载页面数据合并为 allItems，传给虚拟滚动组件
 * - 滚动到接近底部时自动加载下一页（triggerFetch）
 * - 已加载数据由 vue-query 缓存，30s 内不重复请求
 */
interface Options {
  key: string
  url: string
  perPage?: number
  staleTime?: number
  debounceMs?: number
  extraParams?: () => Record<string, any>
}

export function useVirtualScrollList<T>(opts: Options) {
  const { key, url, perPage: defPP = 50, staleTime = 30_000, debounceMs = 300, extraParams } = opts
  const search = ref('')
  const dSearch = ref('')
  const sortBy = ref('')
  const sortOrder = ref<'asc' | 'desc'>('desc')

  let timer: ReturnType<typeof setTimeout> | null = null
  watch(search, (v) => {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => { dSearch.value = v }, debounceMs)
  })

  const qk = computed(() => [
    key, dSearch.value, sortBy.value, sortOrder.value, extraParams?.() ?? {},
  ])

  const {
    data,
    isLoading,
    isFetching,
    isFetchingNextPage,
    hasNextPage,
    fetchNextPage,
  } = useInfiniteQuery({
    queryKey: qk,
    queryFn: async ({ pageParam }) => {
      const r = await get<PaginatedResponse<T>>(url, {
        page: pageParam,
        per_page: defPP,
        search: dSearch.value || undefined,
        sort_by: sortBy.value || undefined,
        sort_order: sortOrder.value || undefined,
        ...extraParams?.(),
      })
      return r
    },
    initialPageParam: 1,
    getNextPageParam: (lastPage) => {
      if (lastPage.current_page < lastPage.pages) return lastPage.current_page + 1
      return undefined
    },
    staleTime,
  })

  const allItems = computed<T[]>(() => {
    const pages = data.value?.pages
    if (!pages) return []
    const result: T[] = []
    for (const page of pages) {
      if (page.items) result.push(...page.items)
    }
    return result
  })

  const total = computed(() => data.value?.pages?.[0]?.total ?? 0)
  const loadedCount = computed(() => allItems.value.length)
  const hasMore = computed(() => hasNextPage.value ?? false)

  function triggerFetch(visibleEndIndex: number) {
    if (!hasNextPage.value || isFetchingNextPage.value) return
    if (visibleEndIndex >= loadedCount.value - 5) {
      fetchNextPage()
    }
  }

  function resetAndSearch(v: string) {
    search.value = v
  }

  function resetFilters() {
    search.value = ''
    dSearch.value = ''
    sortBy.value = ''
    sortOrder.value = 'desc'
  }

  return {
    allItems: readonly(allItems),
    total: readonly(total),
    loadedCount: readonly(loadedCount),
    hasMore: readonly(hasMore),
    isLoading,
    isFetching,
    isFetchingNextPage,
    search: readonly(search),
    sortBy: readonly(sortBy),
    sortOrder: readonly(sortOrder),
    triggerFetch,
    resetAndSearch,
    resetFilters,
    handleSort: (p: string, o: string | null) => {
      sortBy.value = p
      sortOrder.value = o === 'ascending' ? 'asc' : 'desc'
    },
  }
}
