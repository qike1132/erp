import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'

// ---------------------------------------------------------------------------
// 通用逻辑 composables（无 UI，依赖较少）
// ---------------------------------------------------------------------------

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
