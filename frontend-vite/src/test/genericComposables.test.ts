import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'

// ---------------------------------------------------------------------------
// 通用逻辑 composables（无 UI，依赖较少）
// ---------------------------------------------------------------------------

import { usePagedSearch } from '@/composables/usePagedSearch'
import { useDebouncedSearch } from '@/composables/useDebouncedSearch'
import { useDebouncedRef } from '@/composables/useDebouncedRef'

/**
 * 在真实组件实例内运行 composable（onUnmounted 等生命周期钩子需要组件上下文）
 */
function withSetup<T>(composable: () => T): { result: T; wrapper: ReturnType<typeof mount>; unmount: () => void } {
  let result!: T
  const wrapper = mount(
    defineComponent({
      setup() {
        result = composable()
        return () => h('div')
      },
    }),
  )
  return { result, wrapper, unmount: () => wrapper.unmount() }
}

describe('usePagedSearch', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('初始状态：搜索词为空、第 1 页、每页 20 条', () => {
    const { result } = withSetup(() => usePagedSearch())
    expect(result.searchTerm.value).toBe('')
    expect(result.debouncedSearch.value).toBe('')
    expect(result.currentPage.value).toBe(1)
    expect(result.perPage).toBe(20)
  })

  it('输入后 300ms 内不更新防抖值（防止每键入一次就请求）', () => {
    const { result } = withSetup(() => usePagedSearch())
    result.searchTerm.value = 'abc'
    result.onSearchInput()

    vi.advanceTimersByTime(299)
    expect(result.debouncedSearch.value).toBe('')

    vi.advanceTimersByTime(1)
    expect(result.debouncedSearch.value).toBe('abc')
  })

  it('连续输入只触发一次（后一次重置计时器）', () => {
    const { result } = withSetup(() => usePagedSearch())
    result.searchTerm.value = 'a'
    result.onSearchInput()
    vi.advanceTimersByTime(200)
    result.searchTerm.value = 'ab'
    result.onSearchInput()
    vi.advanceTimersByTime(200)
    // 累计 400ms，但第二次输入重置了计时器，此时仍未到 300ms
    expect(result.debouncedSearch.value).toBe('')

    vi.advanceTimersByTime(100)
    expect(result.debouncedSearch.value).toBe('ab')
  })

  it('防抖生效时重置页码到第 1 页', () => {
    const { result } = withSetup(() => usePagedSearch())
    result.currentPage.value = 5
    result.searchTerm.value = 'x'
    result.onSearchInput()
    vi.advanceTimersByTime(300)
    expect(result.currentPage.value).toBe(1)
  })

  it('clearSearch 立即清空三项状态（不等待防抖）', () => {
    const { result } = withSetup(() => usePagedSearch())
    result.searchTerm.value = 'abc'
    result.onSearchInput()
    vi.advanceTimersByTime(300)
    result.currentPage.value = 3

    result.clearSearch()

    expect(result.searchTerm.value).toBe('')
    expect(result.debouncedSearch.value).toBe('')
    expect(result.currentPage.value).toBe(1)
  })

  it('clearSearch 后未到期的旧防抖任务不再回写已清空的值', () => {
    const { result } = withSetup(() => usePagedSearch())
    result.searchTerm.value = 'old'
    result.onSearchInput()          // 启动 300ms 计时器
    result.clearSearch()            // 立即清空
    vi.advanceTimersByTime(300)     // 旧计时器到期

    // 旧任务仍会把 searchTerm（此时为 ''）写入 —— 关键是不能写回 'old'
    expect(result.debouncedSearch.value).not.toBe('old')
  })

  it('组件卸载时清理未触发的防抖任务（不产生悬挂定时器）', () => {
    const clearSpy = vi.spyOn(globalThis, 'clearTimeout')
    const { result, unmount } = withSetup(() => usePagedSearch())
    result.searchTerm.value = 'pending'
    result.onSearchInput()

    const callsBefore = clearSpy.mock.calls.length
    unmount()
    expect(clearSpy.mock.calls.length).toBeGreaterThan(callsBefore)
    clearSpy.mockRestore()
  })
})

describe('useDebouncedSearch', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('默认 300ms 后执行回调', () => {
    const { result } = withSetup(() => useDebouncedSearch())
    const cb = vi.fn()
    result.debounceSearch(cb)

    vi.advanceTimersByTime(299)
    expect(cb).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)
    expect(cb).toHaveBeenCalledTimes(1)
  })

  it('自定义延迟生效', () => {
    const { result } = withSetup(() => useDebouncedSearch(1000))
    const cb = vi.fn()
    result.debounceSearch(cb)
    vi.advanceTimersByTime(999)
    expect(cb).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)
    expect(cb).toHaveBeenCalledTimes(1)
  })

  it('重复调用只有最后一次回调被执行', () => {
    const { result } = withSetup(() => useDebouncedSearch())
    const first = vi.fn()
    const second = vi.fn()

    result.debounceSearch(first)
    vi.advanceTimersByTime(100)
    result.debounceSearch(second)
    vi.advanceTimersByTime(300)

    expect(first).not.toHaveBeenCalled()
    expect(second).toHaveBeenCalledTimes(1)
  })

  it('卸载时清理未触发的回调', () => {
    const { result, unmount } = withSetup(() => useDebouncedSearch())
    const cb = vi.fn()
    result.debounceSearch(cb)
    unmount()
    vi.advanceTimersByTime(1000)
    expect(cb).not.toHaveBeenCalled()
  })
})

describe('useDebouncedRef', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('非 ref 入参降级为取值快照（不抛异常）', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const source = { value: 'init' }
    const debounced = useDebouncedRef(source)

    expect(debounced.value).toBe('init')
    source.value = 'changed'
    vi.advanceTimersByTime(1000)
    // 普通对象无响应式来源，保持快照值；ref 入参的跟随行为见
    // src/test/useDebouncedRef.regression.test.ts
    expect(debounced.value).toBe('init')
    warn.mockRestore()
  })

  it('返回的是 ref（具备 .value 访问形态）', () => {
    const debounced = useDebouncedRef({ value: 'x' })
    expect(debounced).toHaveProperty('value')
    expect(debounced.value).toBe('x')
  })
})

describe('usePermission', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('转发到 auth store 的 hasPermission', async () => {
    const { usePermission } = await import('@/composables/usePermission')
    const { useAuthStore } = await import('@/stores/auth')
    const auth = useAuthStore()
    auth.setUserInfo({
      id: 1, username: 'u', is_super: false, factory: null,
      permissions: ['order:view'],
    })

    const { hasPermission } = usePermission()
    expect(hasPermission('order:view')).toBe(true)
    expect(hasPermission('order:delete')).toBe(false)
  })

  it('超级管理员恒为 true', async () => {
    const { usePermission } = await import('@/composables/usePermission')
    const { useAuthStore } = await import('@/stores/auth')
    useAuthStore().setUserInfo({
      id: 1, username: 'admin', is_super: true, factory: null, permissions: [],
    })

    const { hasPermission } = usePermission()
    expect(hasPermission('any:code')).toBe(true)
  })
})
