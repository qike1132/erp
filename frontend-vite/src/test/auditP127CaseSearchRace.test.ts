/**
 * P1-27 回归：皮套移动端搜索逐字符请求，且旧响应会覆盖新关键词结果。
 *
 * 修复后：搜索框改为 @search 显式提交；onSearch 用请求序号丢弃过期响应。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'

const mocks = vi.hoisted(() => ({
  caseApi: {
    search: vi.fn(),
    inventory: vi.fn(),
  },
}))

vi.mock('@/api', () => ({ caseApi: mocks.caseApi }))
vi.mock('@/views/case/composables/useCaseSettings', async () => {
  const { ref, computed } = await import('vue')
  return {
    useCaseSettings: () => ({
      keyword: ref(''),
      partsFilter: ref('all'),
      products: ref([]),
      filtered: computed(() => []),
      isLoading: ref(false),
      selectedMain: ref(null),
      selectedParts: ref([]),
      loadingTree: ref(false),
      selectProduct: vi.fn(),
      saving: ref(false),
      addPart: vi.fn(),
      removePart: vi.fn(),
    }),
  }
})

import MCaseView from '@/mobile/views/case/MCaseView.vue'
import MSearchBar from '@/mobile/components/MSearchBar.vue'
import type { CaseSearchItem } from '@/api/case'

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: { template: '<div />' } }],
  })
}

const opts = () => ({ global: { plugins: [makeRouter()] } })

function searchItem(id: number, name: string): CaseSearchItem {
  return { id, name, barcode: `B${id}`, current_stock: 10, parent_id: null }
}

function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((res) => { resolve = res })
  return { promise, resolve }
}

describe('P1-27 皮套搜索显式提交与过期响应', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.caseApi.inventory.mockResolvedValue({ inventory: [], total: 0 })
    mocks.caseApi.search.mockResolvedValue([])
  })

  it('输入过程不发请求，@search 提交才查', async () => {
    const wrapper = mount(MCaseView, opts())
    await flushPromises()

    const bar = wrapper.findComponent(MSearchBar)
    mocks.caseApi.search.mockClear()

    bar.vm.$emit('update:modelValue', '鲨')
    await flushPromises()
    expect(mocks.caseApi.search).not.toHaveBeenCalled()

    bar.vm.$emit('update:modelValue', '鲨鱼帽')
    bar.vm.$emit('search', '鲨鱼帽')
    await flushPromises()
    expect(mocks.caseApi.search).toHaveBeenCalledTimes(1)
    expect(mocks.caseApi.search).toHaveBeenCalledWith('鲨鱼帽')
  })

  it('旧搜索响应后到不覆盖新关键词结果', async () => {
    const oldReq = deferred<CaseSearchItem[]>()
    const newReq = deferred<CaseSearchItem[]>()
    mocks.caseApi.search.mockImplementation((q: string) => (q === '旧款' ? oldReq.promise : newReq.promise))

    const wrapper = mount(MCaseView, opts())
    await flushPromises()
    const vm = wrapper.vm as unknown as {
      productQuery: string
      onSearch: () => Promise<void>
    }

    vm.productQuery = '旧款'
    const oldDone = vm.onSearch()
    vm.productQuery = '新款'
    const newDone = vm.onSearch()

    newReq.resolve([searchItem(2, '新款皮套')])
    await newDone
    await flushPromises()
    expect(wrapper.text()).toContain('新款皮套')

    oldReq.resolve([searchItem(1, '旧款皮套')])
    await oldDone
    await flushPromises()
    expect(wrapper.text()).not.toContain('旧款皮套')
    expect(wrapper.text()).toContain('新款皮套')
  })
})
