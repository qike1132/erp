/**
 * useOrderForm —— 可用备货查询的请求序号（2026-10-30 审计 A-M36）
 *
 * 现场：下单页的「可用备货」既决定抵扣量的输入上限，也是「提交前复核」的比较基准。
 * 换产品/换客户时先发的请求可能后到，把 A 产品的可用量写到 B 产品的提示上，
 * 用户照着它填抵扣量 —— 后端按 B 的备货 min() 静默截断，结果少扣且没有任何提示。
 * 这里锁：只接受最后一次请求、且产品/客户未变的结果。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { nextTick } from 'vue'
import { setActivePinia, createPinia } from 'pinia'

const mocks = vi.hoisted(() => ({
  availableStockinsMock: vi.fn(),
  productSearchMock: vi.fn(async () => [] as unknown[]),
  activeNamesMock: vi.fn(async () => [] as unknown[]),
  productListMock: vi.fn(async () => ({ items: [], total: 0 })),
  supplierListMock: vi.fn(async () => ({ suppliers: [], total: 0 })),
}))

vi.mock('@/api', () => ({
  auxApi: {
    productSearch: mocks.productSearchMock,
    availableStockins: mocks.availableStockinsMock,
  },
  customerApi: { activeNames: mocks.activeNamesMock },
  productApi: { list: mocks.productListMock },
  supplierApi: { list: mocks.supplierListMock },
}))

import { useOrderForm } from '@/views/customer-order/composables/useOrderForm'
import type { AvailableStockinItem } from '@/views/customer-order/composables/types'

function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

describe('useOrderForm 可用备货：请求序号', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('换产品后旧请求后到：可用量保持新产品的值', async () => {
    const first = deferred<AvailableStockinItem[]>()
    const second = deferred<AvailableStockinItem[]>()
    mocks.availableStockinsMock
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise)

    const { form, availableStock, fetchAvailableStock } = useOrderForm()
    form.customer = '贝乐'
    await nextTick()

    form.productId = 1
    const p1 = fetchAvailableStock()
    form.productId = 2
    const p2 = fetchAvailableStock()

    second.resolve([{ id: 2, quantity: 5, deducted: 0, available: 5 }])
    await p2
    first.resolve([{ id: 1, quantity: 99, deducted: 0, available: 99 }])
    await p1

    // 无序号守卫时这里会是 99：产品 A 的可用量显示在产品 B 上
    expect(availableStock.value).toBe(5)
  })

  it('换客户后旧请求后到同样被丢弃', async () => {
    const first = deferred<AvailableStockinItem[]>()
    const second = deferred<AvailableStockinItem[]>()
    mocks.availableStockinsMock
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise)

    const { form, availableStock, fetchAvailableStock } = useOrderForm()
    form.customer = '贝乐'
    await nextTick()
    form.productId = 1
    const p1 = fetchAvailableStock()

    // 换客户：watcher 会清空产品，用户重新选回同一个产品再查
    form.customer = '海豚国际'
    await nextTick()
    form.productId = 1
    const p2 = fetchAvailableStock()

    second.resolve([{ id: 1, quantity: 2, deducted: 0, available: 2 }])
    await p2
    first.resolve([{ id: 1, quantity: 40, deducted: 0, available: 40 }])
    await p1

    expect(availableStock.value).toBe(2)
  })

  it('查询失败暴露 stockError，而不是把 0 当成「没有可用备货」', async () => {
    mocks.availableStockinsMock.mockRejectedValue(new Error('boom'))

    const { form, availableStock, stockError, fetchAvailableStock } = useOrderForm()
    form.customer = '贝乐'
    await nextTick()
    form.productId = 1

    await fetchAvailableStock()

    expect(availableStock.value).toBe(0)
    expect(stockError.value).toBe('可用备货查询失败，请重试')
  })

  it('查询成功清空此前的错误提示', async () => {
    mocks.availableStockinsMock.mockRejectedValueOnce(new Error('boom'))
    mocks.availableStockinsMock.mockResolvedValueOnce([
      { id: 1, quantity: 7, deducted: 2, available: 5 },
    ])

    const { form, availableStock, stockError, fetchAvailableStock } = useOrderForm()
    form.customer = '贝乐'
    await nextTick()
    form.productId = 1

    await fetchAvailableStock()
    expect(stockError.value).not.toBe('')

    await fetchAvailableStock()
    expect(stockError.value).toBe('')
    expect(availableStock.value).toBe(5)
  })

  it('未选产品/客户时不发请求，并说明前置条件', async () => {
    const { availableStock, stockError, fetchAvailableStock } = useOrderForm()

    await fetchAvailableStock()

    expect(mocks.availableStockinsMock).not.toHaveBeenCalled()
    expect(availableStock.value).toBe(0)
    expect(stockError.value).toContain('请先选择产品与客户')
  })
})
