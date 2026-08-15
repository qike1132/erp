/**
 * usePatternRoomGroupFilter — 分组列表筛选/搜索 Hook
 *
 * 封装状态筛选、关键词防抖搜索与分组视图翻页。
 * 逻辑自 PatternRoomView.vue 原样搬移。
 */
import { ref } from 'vue'
import { useDebouncedSearch } from '@/composables/useDebouncedSearch'
import type { useCustomerSampling } from './useCustomerSampling'

type GroupHook = ReturnType<typeof useCustomerSampling>

export function usePatternRoomGroupFilter(groupHook: GroupHook) {
  /** 状态筛选：in_progress/completed/cancelled */
  const statusFilter = ref<string>('in_progress')
  /** 搜索关键词 */
  const searchKeyword = ref('')

  function onStatusChange(val: string) {
    statusFilter.value = val
    // 所有状态现在都用分组卡片视图 + 分页，所以直接加载
    groupHook.loadGrouped(searchKeyword.value || undefined, val, 1)
  }

  /** 分组视图翻页 */
  function onGroupPageChange(page: number) {
    if (page === groupHook.currentPage.value) return
    groupHook.loadGrouped(searchKeyword.value || undefined, statusFilter.value, page)
  }

  /** 搜索（防抖） */
  const { debounceSearch } = useDebouncedSearch()
  function onSearch(keyword: string) {
    searchKeyword.value = keyword
    debounceSearch(() => {
      groupHook.loadGrouped(keyword || undefined, statusFilter.value, 1)
    })
  }

  return {
    statusFilter,
    searchKeyword,
    onStatusChange,
    onGroupPageChange,
    onSearch,
  }
}
