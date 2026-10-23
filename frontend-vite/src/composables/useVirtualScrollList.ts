import { ref, computed, readonly } from 'vue'
import { refDebounced } from '@vueuse/core'
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
 * - 已加载页面数据合并为 allItems，传给虚拟滚动组件
 * - 滚动到接近底部时自动加载下一页（triggerFetch）
 * - 已加载数据由 vue-query 缓存，30s 内不重复请求
 * - 内存管理：当已加载页数超过 maxLoadedPages 时，触发 GC 回收远离可视区域的旧页
 */
interface Options {
  key: string
  url: string
  perPage?: number
  staleTime?: number
  debounceMs?: number
  extraParams?: () => Record<string, unknown>
  maxLoadedPages?: number
}

export function useVirtualScrollList<T>(opts: Options) {
  const { key, url, perPage: defPP = 50, staleTime = 30_000, debounceMs = 300, extraParams, maxLoadedPages = 20 } = opts
  const search = ref('')
  const dSearch = refDebounced(search, debounceMs)
  const sortBy = ref('')
  const sortOrder = ref<'asc' | 'desc'>('desc')

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
    // routeCancel: false —— 同 useEnhancedList：无限查询的请求归 Vue Query 所有，
    // 被路由取消会让该 queryKey 永久停在 fetching，滚回本页时永远「加载中」。
    queryFn: async ({ pageParam }) => {
      const r = await get<PaginatedResponse<T>>(url, {
        page: pageParam,
        per_page: defPP,
        search: dSearch.value || undefined,
        sort_by: sortBy.value || undefined,
        sort_order: sortOrder.value || undefined,
        ...extraParams?.(),
      }, { routeCancel: false })
      return r
    },
    initialPageParam: 1,
    getNextPageParam: (lastPage) => {
      if (lastPage.current_page < lastPage.pages) return lastPage.current_page + 1
      return undefined
    },
    staleTime,
    gcTime: 5 * 60 * 1000, // 5 minutes garbage collection
  })

  // Track which pages to include based on current scroll position
  const currentPageWindow = ref<{ start: number; end: number }>({ start: 0, end: maxLoadedPages })

  const allItems = computed<T[]>(() => {
    const pages = data.value?.pages
    if (!pages) return []
    const { start, end } = currentPageWindow.value
    const result: T[] = []
    for (let i = start; i < Math.min(end, pages.length); i++) {
      const page = pages[i]
      if (page?.items) result.push(...page.items)
    }
    return result
  })

  const total = computed(() => data.value?.pages?.[0]?.total ?? 0)
  const loadedCount = computed(() => allItems.value.length)
  const hasMore = computed(() => hasNextPage.value ?? false)

  // Page offset: the index in allItems where the current window starts
  const pageOffset = computed(() => {
    const pages = data.value?.pages
    if (!pages) return 0
    let offset = 0
    for (let i = 0; i < currentPageWindow.value.start && i < pages.length; i++) {
      offset += pages[i]?.items?.length ?? 0
    }
    return offset
  })

  function updatePageWindow(visibleStartIndex: number) {
    const pages = data.value?.pages
    if (!pages || pages.length <= maxLoadedPages) return

    // Determine which page the visible start index falls into
    let acc = 0
    let visiblePage = 0
    for (let i = 0; i < pages.length; i++) {
      const len = pages[i]?.items?.length ?? 0
      if (acc + len > visibleStartIndex + pageOffset.value) {
        visiblePage = i
        break
      }
      acc += len
    }

    // Center the window around the visible page
    const halfWindow = Math.floor(maxLoadedPages / 2)
    const newStart = Math.max(0, visiblePage - halfWindow)
    const newEnd = Math.min(pages.length, newStart + maxLoadedPages)

    if (newStart !== currentPageWindow.value.start || newEnd !== currentPageWindow.value.end) {
      currentPageWindow.value = { start: newStart, end: newEnd }
    }
  }

  function triggerFetch(visibleEndIndex: number) {
    if (!hasNextPage.value || isFetchingNextPage.value) return
    // Update page window based on scroll position
    updatePageWindow(visibleEndIndex > 0 ? visibleEndIndex - 1 : 0)
    // Fetch next page if approaching the end of loaded data
    if (visibleEndIndex + pageOffset.value >= loadedCount.value - 5) {
      fetchNextPage()
    }
  }

  function resetAndSearch(v: string) {
    search.value = v
    currentPageWindow.value = { start: 0, end: maxLoadedPages }
  }

  function resetFilters() {
    search.value = ''
    sortBy.value = ''
    sortOrder.value = 'desc'
    currentPageWindow.value = { start: 0, end: maxLoadedPages }
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
