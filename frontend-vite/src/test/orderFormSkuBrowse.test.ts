/**
 * useOrderForm —— SKU 浏览列表（弹窗「点开就列该客户可见的 SKU」）
 *
 * 需求（2026-10-10，方案 B）：产品名称字段改成点击弹窗，弹窗点开时还没有关键字，
 * 需要一次把当前客户可见的 SKU 列出来（浏览），与关键字搜索共用一个后端端点。
 *
 * 锁的行为：
 *   1. 有客户 → 调 `/aux/product-search`，**空关键字 + 该客户 + 大 limit**；
 *   2. 没客户 → 一个请求都不发，直接把 skuListError 摆成「请先选择客户」；
 *   3. 请求失败 → skuListError 说「加载失败」，不能与「该客户没有产品」混为一谈。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const mocks = vi.hoisted(() => ({
  productSearchMock: vi.fn(async () => [] as unknown[]),
  activeNamesMock: vi.fn(async () => [] as unknown[]),
  productListMock: vi.fn(async () => ({ items: [], total: 0 })),
  supplierListMock: vi.fn(async () => ({ suppliers: [], total: 0 })),
}))

vi.mock('@/api', () => ({
  auxApi: { productSearch: mocks.productSearchMock },
  customerApi: { activeNames: mocks.activeNamesMock },
  productApi: { list: mocks.productListMock },
  supplierApi: { list: mocks.supplierListMock },
}))

import { useOrderForm } from '@/views/customer-order/composables/useOrderForm'

describe('useOrderForm — SKU 浏览列表', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mocks.productSearchMock.mockReset()
    mocks.productSearchMock.mockResolvedValue([])
    mocks.activeNamesMock.mockClear()
  })

  it('有客户时用「空关键字 + 该客户 + 大 limit」拉浏览列表', async () => {
    mocks.productSearchMock.mockResolvedValue([
      { id: 7, name: '小熊毛绒玩具 20cm', barcode: '690', price: 1, current_stock: 3 },
    ])
    const { form, fetchSkuList, skuListError } = useOrderForm()
    form.customer = '贝乐'

    const list = await fetchSkuList()

    expect(mocks.productSearchMock).toHaveBeenCalledWith('', { customer: '贝乐', limit: 200 })
    expect(list).toEqual([{ value: '小熊毛绒玩具 20cm', id: 7, name: '小熊毛绒玩具 20cm', barcode: '690' }])
    expect(skuListError.value).toBe('')
  })

  it('没选客户时一个请求都不发，并给出「请先选择客户」', async () => {
    const { fetchSkuList, skuListError } = useOrderForm()

    const list = await fetchSkuList()

    expect(list).toEqual([])
    expect(mocks.productSearchMock).not.toHaveBeenCalled()
    expect(skuListError.value).toBe('请先选择客户')
  })

  it('请求失败时说「加载失败」，不说成「该客户没有产品」', async () => {
    mocks.productSearchMock.mockRejectedValue(new Error('boom'))
    const { form, fetchSkuList, skuListError } = useOrderForm()
    form.customer = '贝乐'

    const list = await fetchSkuList()

    expect(list).toEqual([])
    expect(skuListError.value).toContain('加载失败')
  })

  it('关键字搜索的返回结构与浏览一致（同一个映射，OCR 链路共用不能漂移）', async () => {
    mocks.productSearchMock.mockResolvedValue([
      { id: 9, name: '独角兽挂件 8cm', barcode: null, price: 0, current_stock: 0 },
    ])
    const { form, searchProducts } = useOrderForm()
    form.customer = '贝乐'

    const list = await searchProducts('挂件')

    expect(list).toEqual([{ value: '独角兽挂件 8cm', id: 9, name: '独角兽挂件 8cm', barcode: '' }])
  })
})
