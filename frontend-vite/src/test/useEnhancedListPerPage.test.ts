/**
 * useEnhancedList —— 每页条数（perPage）持久化
 *
 * 缺陷背景（2026-10-09 用户报告）：/product 选 10 条/页后刷新，变回 20。
 * 根因：perPage 只是内存 ref(20)，无任何持久化。
 * 修复：localStorage 按 key 存取（list-per-page:<key>），回读校验白名单，
 * 防手改脏值进请求参数。
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { VueQueryPlugin, QueryClient } from '@tanstack/vue-query'
import { defineComponent, h } from 'vue'
import { useEnhancedList } from '@/composables/useEnhancedList'

function mountList(key = 'probe-list') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  let perPage: { value: number } | null = null
  const Probe = defineComponent({
    setup() {
      const list = useEnhancedList<{ id: number }>({
        key,
        url: '/probe/list',
        perPage: 20,
      })
      perPage = list.perPage as unknown as { value: number }
      return () => h('div', `total=${list.total.value}`)
    },
  })
  mount(Probe, { global: { plugins: [[VueQueryPlugin, { queryClient: client }]] } })
  return { perPage: perPage! }
}

beforeEach(() => {
  localStorage.clear()
})

describe('useEnhancedList perPage 持久化', () => {
  it('默认 20，没有存储时不读 localStorage', () => {
    const { perPage } = mountList()
    expect(perPage.value).toBe(20)
    expect(localStorage.getItem('list-per-page:probe-list')).toBeNull()
  })

  it('handleSizeChange(10) 后写回 localStorage', () => {
    // 直接从真实流程走：挂载 → 改每页条数 → 断言存储
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    let handleSizeChange: ((v: number) => void) | null = null
    const Probe = defineComponent({
      setup() {
        const list = useEnhancedList<{ id: number }>({ key: 'probe-list', url: '/probe/list', perPage: 20 })
        handleSizeChange = list.handleSizeChange
        return () => h('div')
      },
    })
    mount(Probe, { global: { plugins: [[VueQueryPlugin, { queryClient: client }]] } })
    handleSizeChange!(10)

    expect(localStorage.getItem('list-per-page:probe-list')).toBe('10')
  })

  it('localStorage 里有合法值时，初次挂载就用它', () => {
    localStorage.setItem('list-per-page:probe-list', '50')
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    let perPage: { value: number } | null = null
    const Probe = defineComponent({
      setup() {
        const list = useEnhancedList<{ id: number }>({ key: 'probe-list', url: '/probe/list', perPage: 20 })
        perPage = list.perPage as unknown as { value: number }
        return () => h('div')
      },
    })
    mount(Probe, { global: { plugins: [[VueQueryPlugin, { queryClient: client }]] } })
    expect(perPage!.value).toBe(50)
  })

  it('localStorage 脏值（不在白名单）被拒，回落默认 20', () => {
    localStorage.setItem('list-per-page:probe-list', '-1')
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    let perPage: { value: number } | null = null
    const Probe = defineComponent({
      setup() {
        const list = useEnhancedList<{ id: number }>({ key: 'probe-list', url: '/probe/list', perPage: 20 })
        perPage = list.perPage as unknown as { value: number }
        return () => h('div')
      },
    })
    mount(Probe, { global: { plugins: [[VueQueryPlugin, { queryClient: client }]] } })
    expect(perPage!.value).toBe(20)
  })

  it('不同列表 key 互不串用', () => {
    localStorage.setItem('list-per-page:other-list', '100')
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    let perPage: { value: number } | null = null
    const Probe = defineComponent({
      setup() {
        const list = useEnhancedList<{ id: number }>({ key: 'probe-list', url: '/probe/list', perPage: 20 })
        perPage = list.perPage as unknown as { value: number }
        return () => h('div')
      },
    })
    mount(Probe, { global: { plugins: [[VueQueryPlugin, { queryClient: client }]] } })
    expect(perPage!.value).toBe(20)
  })

  it('localStorage 不可用（抛异常）时不崩，用默认值', () => {
    const original = window.localStorage
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      get() { throw new Error('disabled') },
    })
    try {
      const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
      let perPage: { value: number } | null = null
      const Probe = defineComponent({
        setup() {
          const list = useEnhancedList<{ id: number }>({ key: 'probe-list', url: '/probe/list', perPage: 20 })
          perPage = list.perPage as unknown as { value: number }
          return () => h('div')
        },
      })
      mount(Probe, { global: { plugins: [[VueQueryPlugin, { queryClient: client }]] } })
      expect(perPage!.value).toBe(20)
    } finally {
      Object.defineProperty(window, 'localStorage', { configurable: true, value: original })
    }
  })
})
