import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { usePagedSearch } from '../composables/usePagedSearch'

/** 测试宿主组件：在组件上下文中调用 composable，保证 onUnmounted 有活动实例 */
const Host = defineComponent({
  setup() {
    const search = usePagedSearch()
    return { search }
  },
  template: '<div />',
})

function createHost() {
  const wrapper = mount(Host)
  return wrapper.vm.search
}

describe('usePagedSearch（列表页搜索+分页公共状态）', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('初始状态：搜索词为空、第 1 页、每页 20 条', () => {
    const s = createHost()
    expect(s.searchTerm.value).toBe('')
    expect(s.currentPage.value).toBe(1)
    expect(s.perPage).toBe(20)
    expect(s.debouncedSearch.value).toBe('')
  })

  it('输入后 300ms 防抖才更新关键词，并重置到第 1 页', async () => {
    const s = createHost()
    s.searchTerm.value = '客户A'
    s.currentPage.value = 3

    s.onSearchInput()
    // 防抖未到期：关键词未更新
    vi.advanceTimersByTime(200)
    expect(s.debouncedSearch.value).toBe('')
    expect(s.currentPage.value).toBe(3)

    // 防抖到期：关键词更新 + 页码重置
    vi.advanceTimersByTime(150)
    expect(s.debouncedSearch.value).toBe('客户A')
    expect(s.currentPage.value).toBe(1)
  })

  it('连续输入只触发最后一次防抖', async () => {
    const s = createHost()
    const values = ['客', '客户', '客户B']
    for (const v of values) {
      s.searchTerm.value = v
      s.onSearchInput()
      vi.advanceTimersByTime(100) // 每次都在 300ms 内
    }
    vi.advanceTimersByTime(300)
    expect(s.debouncedSearch.value).toBe('客户B')
  })

  it('clearSearch 清空搜索词与关键词并重置页码', () => {
    const s = createHost()
    s.searchTerm.value = 'x'
    s.debouncedSearch.value = 'x'
    s.currentPage.value = 5

    s.clearSearch()
    expect(s.searchTerm.value).toBe('')
    expect(s.debouncedSearch.value).toBe('')
    expect(s.currentPage.value).toBe(1)
  })

  it('卸载时清理未触发的防抖定时器', async () => {
    const wrapper = mount(Host)
    const s = wrapper.vm.search
    s.searchTerm.value = '清理测试'
    s.onSearchInput()
    // 卸载组件触发 onUnmounted 清理
    wrapper.unmount()
    // 防抖到期后不应再更新（定时器已清理）
    vi.advanceTimersByTime(500)
    expect(s.debouncedSearch.value).toBe('')
  })
})
