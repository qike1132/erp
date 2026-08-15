import { ref, onUnmounted } from 'vue'

/**
 * 列表页「搜索 + 服务端分页」公共状态
 *
 * 封装搜索词（实时绑定输入框）、300ms 防抖关键词、当前页码、每页条数，
 * 以及防抖输入、清空搜索并重置页码、卸载时清理定时器等逻辑。
 * 供 ApprovalView / SupplierView 等列表页共用。
 */
export function usePagedSearch() {
  const searchTerm = ref('')
  const currentPage = ref(1)
  const perPage = 20

  let searchTimer: ReturnType<typeof setTimeout> | null = null
  const debouncedSearch = ref('')

  /** 搜索输入防抖处理（300ms 延迟），防抖后重置到第一页 */
  function onSearchInput() {
    if (searchTimer) clearTimeout(searchTimer)
    searchTimer = setTimeout(() => {
      debouncedSearch.value = searchTerm.value
      currentPage.value = 1
    }, 300)
  }

  /** 清除搜索条件并重置页码 */
  function clearSearch() {
    searchTerm.value = ''
    debouncedSearch.value = ''
    currentPage.value = 1
  }

  onUnmounted(() => {
    if (searchTimer) clearTimeout(searchTimer)
  })

  return { searchTerm, currentPage, perPage, debouncedSearch, onSearchInput, clearSearch }
}
