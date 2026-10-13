/**
 * 产品页搜索框 —— 输入关键词并回车后，关键词必须真正提交给列表查询
 *
 * 缺陷背景（2026-10-13 用户报告）：/product 搜索框输入后毫无反应。
 * 根因：ProductTable 把 UiSearchInput 的 modelValue 绑到 useEnhancedList 暴露的
 * readonly(search)，`@update:model-value="searchTerm = $event"` 对 readonly ref 赋值
 * 被 Vue 静默忽略（仅 dev 警告），modelValue 永远停在 ''；回车/点放大镜时
 * UiSearchInput `emit('search', props.modelValue)` 交出空串，列表永不按关键词过滤。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { VueQueryPlugin, QueryClient } from '@tanstack/vue-query'

const { getMock } = vi.hoisted(() => ({
  getMock: vi.fn(async (_url: string, _params?: Record<string, unknown>) => ({
    items: [], total: 0, page: 1, per_page: 20, pages: 0,
  })),
}))

vi.mock('@/api/request', () => ({
  get: getMock,
  post: vi.fn(),
  put: vi.fn(),
  del: vi.fn(),
  resolveStaticUrl: (u: string | null | undefined) => u ?? '',
}))

vi.mock('@/stores/catalog', () => ({
  useCatalogStore: () => ({
    activeCustomerNames: [],
    ensureActiveCustomerNames: vi.fn(async () => []),
  }),
}))

import ProductTable from '@/views/product/components/ProductTable.vue'
import UiSearchInput from '@/components/ui/UiSearchInput.vue'

function mountTable() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(ProductTable, {
    props: { actionId: null },
    global: {
      plugins: [[VueQueryPlugin, { queryClient: client }]],
      stubs: { UiDataTable: true, UiSelect: true, FontAwesomeIcon: true },
    },
  })
}

/** 找到搜索框输入元素并模拟「输入 + 回车」 */
async function typeAndEnter(wrapper: ReturnType<typeof mountTable>, term: string) {
  const search = wrapper.findComponent(UiSearchInput)
  const input = search.find('input')
  await input.setValue(term)
  await input.trigger('keydown', { key: 'Enter' })
  return search
}

beforeEach(() => {
  getMock.mockClear()
})

describe('产品页搜索框', () => {
  it('输入关键词回车后，search 事件带出真实关键词（而非空串）', async () => {
    const wrapper = mountTable()
    const search = await typeAndEnter(wrapper, 'ABC')
    expect(search.emitted('search')).toEqual([['ABC']])
  })

  it('输入关键词回车后，列表请求带 search=关键词', async () => {
    const wrapper = mountTable()
    await typeAndEnter(wrapper, 'ABC')
    await new Promise((r) => setTimeout(r, 400)) // useEnhancedList 防抖 300ms
    await flushPromises()
    const searches = getMock.mock.calls
      .filter((c) => c[0] === '/products/list')
      .map((c) => c[1]?.search)
    expect(searches).toContain('ABC')
  })
})
