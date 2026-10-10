/**
 * ProductPickerDialog —— 下单页「选择产品」弹窗
 *
 * 需求（2026-10-10 用户裁定，方案 B）：产品名称字段整块可点，点开弹窗；
 * 弹窗里**浏览**（列出当前客户可见的全部 SKU）与**关键字搜索**两种用法在同一个地方。
 *
 * 锁的行为：
 *   1. 点开就先列该客户可见的 SKU（空关键字 → 走 fetchSkuList，不是搜索）；
 *   2. 输入关键字 → 走 searchProducts，并且不再打浏览请求；
 *   3. 清空关键字 → 回到浏览列表；
 *   4. 还没选客户时显示「请先选择客户」，不是「暂无产品」——两者对用户的下一步完全不同；
 *   5. 点击一行 = 选中并关闭（单选）。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ProductPickerDialog from '@/views/customer-order/components/ProductPickerDialog.vue'

const SKUS = [
  { value: '小熊毛绒玩具 20cm', id: 1, name: '小熊毛绒玩具 20cm' },
  { value: '卡通抱枕 40×40', id: 2, name: '卡通抱枕 40×40' },
]

function mountPicker(overrides: Record<string, unknown> = {}) {
  const fetchSkuList = vi.fn(async () => [...SKUS])
  const searchProducts = vi.fn(async () => [] as typeof SKUS)
  const wrapper = mount(ProductPickerDialog, {
    props: {
      open: true,
      customerName: '贝乐',
      fetchSkuList,
      searchProducts,
      skuListError: '',
      searchFailed: false,
      'onUpdate:open': () => {},
      onSelect: () => {},
      ...overrides,
    },
    global: {
      stubs: {
        UiDialog: { props: ['open'], template: '<div v-if="open" class="ui-dialog-stub"><slot /></div>' },
      },
    },
  })
  return { wrapper, fetchSkuList, searchProducts }
}

/** 输入关键字并跨过防抖 */
async function typeSearch(wrapper: ReturnType<typeof mountPicker>['wrapper'], text: string) {
  await wrapper.find('.pp-search').setValue(text)
  vi.advanceTimersByTime(400)
  await flushPromises()
}

describe('ProductPickerDialog', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('点开就先列出当前客户可见的 SKU（走浏览，不是搜索）', async () => {
    const { wrapper, fetchSkuList, searchProducts } = mountPicker()
    await flushPromises()

    expect(fetchSkuList).toHaveBeenCalledTimes(1)
    expect(searchProducts).not.toHaveBeenCalled()
    expect(wrapper.findAll('.pp-item').map((i) => i.text())).toEqual([
      '小熊毛绒玩具 20cm', '卡通抱枕 40×40',
    ])
  })

  it('输入关键字走搜索，且不再打浏览请求', async () => {
    const { wrapper, fetchSkuList, searchProducts } = mountPicker()
    await flushPromises()
    fetchSkuList.mockClear()
    searchProducts.mockResolvedValue([{ value: '独角兽挂件 8cm', id: 9, name: '独角兽挂件 8cm' }])

    await typeSearch(wrapper, '挂件')

    expect(searchProducts).toHaveBeenCalledWith('挂件')
    expect(fetchSkuList).not.toHaveBeenCalled()
    expect(wrapper.findAll('.pp-item').map((i) => i.text())).toEqual(['独角兽挂件 8cm'])
  })

  it('清空关键字回到浏览列表', async () => {
    const { wrapper, fetchSkuList } = mountPicker()
    await flushPromises()
    await typeSearch(wrapper, '挂件')
    fetchSkuList.mockClear()

    await typeSearch(wrapper, '')

    expect(fetchSkuList).toHaveBeenCalledTimes(1)
    expect(wrapper.findAll('.pp-item')).toHaveLength(2)
  })

  it('点击一行 = 选中并关闭', async () => {
    const { wrapper } = mountPicker()
    await flushPromises()

    await wrapper.findAll('.pp-item')[1]!.trigger('click')

    expect(wrapper.emitted('select')?.[0]).toEqual([SKUS[1]])
    expect(wrapper.emitted('update:open')?.[0]).toEqual([false])
  })

  it('还没选客户时提示「请先选择客户」，而不是「暂无产品」', async () => {
    const { wrapper, fetchSkuList } = mountPicker({ customerName: '', skuListError: '请先选择客户' })
    await flushPromises()

    expect(fetchSkuList).not.toHaveBeenCalled()
    expect(wrapper.find('.pp-empty').text()).toContain('请先选择客户')
    expect(wrapper.findAll('.pp-item')).toHaveLength(0)
  })

  it('搜索无结果时提示「无匹配结果」', async () => {
    const { wrapper, searchProducts } = mountPicker()
    await flushPromises()
    searchProducts.mockResolvedValue([])

    await typeSearch(wrapper, '不存在的东西')

    expect(wrapper.find('.pp-empty').text()).toContain('无匹配结果')
  })

  it('搜索失败时提示「搜索失败」，不与「无匹配」混淆', async () => {
    const { wrapper } = mountPicker({ searchFailed: true })
    await flushPromises()

    await typeSearch(wrapper, '挂件')

    expect(wrapper.find('.pp-empty').text()).toContain('搜索失败')
  })
})
