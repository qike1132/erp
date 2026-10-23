import { ref, computed, watch, readonly } from 'vue'
import { refDebounced } from '@vueuse/core'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { get } from '@/api/request'
import type { PaginatedResponse } from '@/types'

interface Options {
  key: string; url: string; perPage?: number; staleTime?: number
  prefetchPages?: number; debounceMs?: number; extraParams?: () => Record<string, unknown>
  enableKeyset?: boolean
}

/** 每页条数合法白名单：localStorage 可能被手改成任意值，回读必须校验 */
const PER_PAGE_OPTIONS = [10, 20, 50, 100]

function loadStoredPerPage(key: string): number | null {
  try {
    const raw = localStorage.getItem(`list-per-page:${key}`)
    if (!raw) return null
    const v = Number(raw)
    if (PER_PAGE_OPTIONS.includes(v)) return v
  } catch { /* 隐私模式等 localStorage 不可用：退回默认值 */ }
  return null
}

function storePerPage(key: string, v: number) {
  try {
    localStorage.setItem(`list-per-page:${key}`, String(v))
  } catch { /* 写失败不影响分页功能 */ }
}

export function useEnhancedList<T>(opts: Options) {
  const { key, url, perPage: defPP = 20, staleTime = 30_000, prefetchPages = 1, debounceMs = 300, extraParams, enableKeyset = false } = opts
  const qc = useQueryClient()
  const page = ref(1), perPage = ref(loadStoredPerPage(key) ?? defPP), search = ref('')
  const dSearch = refDebounced(search, debounceMs)
  const sortBy = ref(''), sortOrder = ref<'asc'|'desc'>('desc'), total = ref(0)
  const keysetCursor = ref<string | number | undefined>(undefined)

  watch(dSearch, () => { page.value = 1; keysetCursor.value = undefined })

  // extraParams 变化（如筛选切换）也要重置页码：queryKey 会变并触发新查询，
  // 但旧 page 若超出新结果页数会拿到空页。只在值真正变化时重置（首次运行跳过）。
  if (extraParams) {
    watch(extraParams, (n, o) => {
      if (JSON.stringify(n) !== JSON.stringify(o)) { page.value = 1; keysetCursor.value = undefined }
    })
  }

  const qk = computed(() => [key, page.value, perPage.value, dSearch.value, sortBy.value, sortOrder.value, keysetCursor.value, extraParams?.() ?? {}])
  const qp = computed(() => ({
    page: page.value, per_page: perPage.value, search: dSearch.value || undefined,
    sort_by: sortBy.value || undefined, sort_order: sortOrder.value || undefined,
    ...(enableKeyset && keysetCursor.value != null ? { keyset_cursor: keysetCursor.value } : {}),
    ...extraParams?.()
  }))

  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: qk,
    // routeCancel: false —— 查询请求归 Vue Query 缓存所有，不属于任何路由。
    // 默认参与路由取消时，请求在途中切走页面会被 abort，而 _silenceCanceled 把取消
    // 变成永不 settle 的 Promise → 该 queryKey 永久停在 fetchStatus='fetching'，
    // 用户再切回来时 useQuery 不复用/不重取，页面永远显示「加载中」且刷新也救不回
    // （2026-10-22 登录后仪表盘无数据是同源事故，这里覆盖全部列表页）。
    queryFn: async () => { const r = await get<PaginatedResponse<T>>(url, qp.value, { routeCancel: false }); total.value = r.total ?? 0; return r },
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
          queryFn: () => get<PaginatedResponse<T>>(url, { ...qp.value, page: np, keyset_cursor: undefined }, { routeCancel: false }),
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
    handleSizeChange: (v: number) => { perPage.value = v; page.value = 1; keysetCursor.value = undefined; storePerPage(key, v) },
    handleSort: (p: string, o: string|null) => { sortBy.value = p; sortOrder.value = o === 'ascending' ? 'asc' : 'desc'; page.value = 1; keysetCursor.value = undefined },
    handleSearch: (v: string) => { search.value = v },
    resetFilters: () => { search.value = ''; sortBy.value = ''; sortOrder.value = 'desc'; page.value = 1; keysetCursor.value = undefined },
  }
}
