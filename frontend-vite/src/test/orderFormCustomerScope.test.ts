/**
 * useOrderForm —— 产品搜索按客户过滤（试点：下单页）
 *
 * 需求（2026-10-09）：下单页先选客户再选产品，产品下拉只列属于该客户（或未挂客户）
 * 的 SKU，避免甲客户选到乙客户的专属 SKU。
 *
 * 这里锁两件事：
 *   1. 搜索请求把当前客户带给后端（不传客户 = 不过滤，保持改造前的行为）；
 *   2. **切换客户时清掉已选产品** —— 否则下拉里还留着上一个客户的结果，
 *      用户可能在没重新输入的情况下选中一个不属于新客户的 SKU，正好是本次要防的事。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { nextTick } from 'vue'
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

describe('useOrderForm — 产品搜索按客户过滤', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mocks.productSearchMock.mockClear()
    mocks.activeNamesMock.mockClear()
  })

  it('搜索时把当前客户一起传给后端', async () => {
    const { form, searchProducts } = useOrderForm()
    form.customer = '贝乐'

    await searchProducts('小熊')

    expect(mocks.productSearchMock).toHaveBeenCalledWith('小熊', { customer: '贝乐' })
  })

  it('未选客户时不带客户参数（不过滤，与改造前一致）', async () => {
    const { searchProducts } = useOrderForm()

    await searchProducts('小熊')

    expect(mocks.productSearchMock).toHaveBeenCalledWith('小熊', { customer: undefined })
  })

  it('切换客户会清掉已选产品，避免把上一个客户的结果当成新客户的', async () => {
    const { form } = useOrderForm()
    form.customer = '贝乐'
    form.productId = 12
    form.productSearch = '小熊毛绒玩具'
    await nextTick()

    form.customer = '海豚国际'
    await nextTick()

    expect(form.productId).toBe(0)
    expect(form.productSearch).toBe('')
  })

  it('客户没变时不误清已选产品', async () => {
    const { form } = useOrderForm()
    form.customer = '贝乐'
    await nextTick()
    form.productId = 12
    form.productSearch = '小熊毛绒玩具'

    await nextTick()

    expect(form.productId).toBe(12)
    expect(form.productSearch).toBe('小熊毛绒玩具')
  })
})
