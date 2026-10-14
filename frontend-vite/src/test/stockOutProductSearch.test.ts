/**
 * 出货页「产品名称」搜索 / 浏览 —— 与客户订单页同款能力。
 *
 * 锁的行为：
 *   1. 有客户 → 浏览调 `/aux/product-search`（空关键字 + 该客户 + 大 limit）；
 *   2. 没客户 → 一个请求都不发，文案是「请先选择客户」；
 *   3. 请求失败 → 文案是「加载失败」，不能与「该客户没有产品」混为一谈；
 *   4. 搜索带当前客户 → 只搜该客户可见范围。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { reactive } from 'vue'

const mocks = vi.hoisted(() => ({
  productSearchMock: vi.fn(async () => [] as unknown[]),
}))

vi.mock('@/api', () => ({
  auxApi: { productSearch: mocks.productSearchMock },
}))

import { useStockOutProductSearch } from '@/views/stock/composables/useStockOutProductSearch'

function makeForm(customer = '', search = '') {
  return reactive({ customer, search })
}

describe('useStockOutProductSearch — SKU 搜索 / 浏览', () => {
  beforeEach(() => {
    mocks.productSearchMock.mockReset()
    mocks.productSearchMock.mockResolvedValue([])
  })

  it('有客户时用「空关键字 + 该客户 + 大 limit」拉浏览列表', async () => {
    mocks.productSearchMock.mockResolvedValue([
      { id: 7, name: '小熊毛绒玩具 20cm', barcode: '690' },
    ])
    const form = makeForm('贝乐')
    const { fetchSkuList, skuListError } = useStockOutProductSearch(form)

    const list = await fetchSkuList()

    expect(mocks.productSearchMock).toHaveBeenCalledWith('', { customer: '贝乐', limit: 200 })
    expect(list).toEqual([{ id: 7, name: '小熊毛绒玩具 20cm', barcode: '690' }])
    expect(skuListError.value).toBe('')
  })

  it('没选客户时一个请求都不发，并给出「请先选择客户」', async () => {
    const form = makeForm('')
    const { fetchSkuList, skuListError, productEmptyText } = useStockOutProductSearch(form)

    const list = await fetchSkuList()

    expect(list).toEqual([])
    expect(mocks.productSearchMock).not.toHaveBeenCalled()
    expect(skuListError.value).toBe('请先选择客户')
    expect(productEmptyText.value).toBe('请先选择客户')
  })

  it('浏览失败时说「加载失败」，不说成「该客户没有产品」', async () => {
    mocks.productSearchMock.mockRejectedValue(new Error('boom'))
    const form = makeForm('贝乐')
    const { fetchSkuList, skuListError } = useStockOutProductSearch(form)

    await fetchSkuList()

    expect(skuListError.value).toContain('加载失败')
  })

  it('搜索时带上当前客户，只搜该客户可见范围', async () => {
    mocks.productSearchMock.mockResolvedValue([
      { id: 9, name: '独角兽挂件 18cm', barcode: '' },
    ])
    const form = makeForm('贝乐', '挂件')
    const { searchProducts } = useStockOutProductSearch(form)

    const list = await searchProducts('挂件')

    expect(mocks.productSearchMock).toHaveBeenCalledWith('挂件', { customer: '贝乐' })
    expect(list).toHaveLength(1)
  })

  it('搜索失败时下拉文案是「搜索失败，请重试」', async () => {
    mocks.productSearchMock.mockRejectedValue(new Error('boom'))
    const form = makeForm('贝乐', '挂件')
    const { searchProducts, productEmptyText } = useStockOutProductSearch(form)

    await searchProducts('挂件')

    expect(productEmptyText.value).toBe('搜索失败，请重试')
  })
})
