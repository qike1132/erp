/**
 * 回归守卫：客户订单写入后必须失效「关联页面」的查询缓存。
 *
 * 缺陷背景（2026-09-30）：客户订单的删除 / 编辑数量 / 抵扣 等写路径成功后只调用
 * `invalidateStockDataQueries()`，而该清单只覆盖库存域
 * （orders-list / stockins-list / stockouts-list / inventory / report-data）。
 *
 * 贝莱订单（beile-orders）、外包订单（outsource-orders）、采购
 * （purchase-orders-list / unprocessed-orders / completed-orders-list）的 query key
 * 从未被失效。这些 query 的 staleTime=30s、gcTime=60s、refetchOnWindowFocus=false，
 * 且经 persistQueryClient 持久化到 sessionStorage —— 于是用户切过去时命中「新鲜」缓存，
 * **根本不发请求**，页面停留在删除/改数量之前的旧数据。
 *
 * 本文件锁死不变量：客户订单任一写路径成功后，三个关联页面的 query key 必须被失效。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

const mocks = vi.hoisted(() => ({
  invalidateQueries: vi.fn(),
  orderDelete: vi.fn(),
  orderUpdate: vi.fn(),
  stockinEdit: vi.fn(),
  stockinDelete: vi.fn(),
}))

vi.mock('@/api', () => ({
  orderApi: {
    delete: mocks.orderDelete,
    update: mocks.orderUpdate,
    updateDeduct: vi.fn(),
  },
  auxApi: { availableStockins: vi.fn(async () => []) },
  stockApi: {
    editStockin: mocks.stockinEdit,
    deleteStockin: mocks.stockinDelete,
  },
}))

vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))

vi.mock('@tanstack/vue-query', () => ({
  useQueryClient: () => ({ invalidateQueries: mocks.invalidateQueries }),
}))

import { useOrderDelete } from '@/views/customer-order/composables/useOrderDelete'
import { useOrderDetailEdit } from '@/views/customer-order/composables/useOrderDetailEdit'
import { useStockinEdit } from '@/views/customer-order/composables/useStockinEdit'

/** 三个关联页面实际使用的 query key 前缀 */
const CROSS_PAGE_KEYS = [
  'beile-orders',           // /beile-order 贝莱（湖北）订单
  'outsource-orders',       // /outsource 外包订单
  'purchase-orders-list',   // /purchase 采购订单
  'unprocessed-orders',     // /purchase 待审核
  'completed-orders-list',  // /purchase 已完成
] as const

/** 收集本次失效动作覆盖到的所有 query key 前缀 */
function invalidatedKeys(): string[] {
  return mocks.invalidateQueries.mock.calls.map((c) => String(c[0]?.queryKey?.[0]))
}

function expectCrossPageInvalidated(action: string) {
  const keys = invalidatedKeys()
  const missing = CROSS_PAGE_KEYS.filter((k) => !keys.includes(k))
  expect(
    missing,
    `${action} 后未失效关联页面缓存：${missing.join(', ')}；实际失效=${JSON.stringify(keys)}`,
  ).toEqual([])
}

const confirmDialog = {
  confirm: vi.fn(async () => true),
}

beforeEach(() => {
  vi.clearAllMocks()
  confirmDialog.confirm.mockResolvedValue(true)
  mocks.orderDelete.mockResolvedValue({ message: '订单删除成功' })
  mocks.orderUpdate.mockResolvedValue({})
})

describe('客户订单写入 → 关联页面缓存失效', () => {
  it('删除订单后，贝莱/外包/采购页面缓存必须一并失效', async () => {
    const { handleDeleteOrder } = useOrderDelete(async () => {}, confirmDialog)

    await handleDeleteOrder({ id: 1, order_no: 'CO-001' } as never)

    expect(mocks.orderDelete).toHaveBeenCalledWith(1)
    expectCrossPageInvalidated('删除订单')
  })

  it('编辑订单数量后，贝莱/外包/采购页面缓存必须一并失效', async () => {
    const edit = useOrderDetailEdit(async () => {})
    edit.detailData.value = { id: 2, quantity: 5, deduct_quantity: 0, note: '' } as never
    edit.editForm.quantity = 9

    await edit.saveEditOrder()

    expect(mocks.orderUpdate).toHaveBeenCalled()
    expectCrossPageInvalidated('编辑订单数量')
  })

  it('编辑备货（入库记录）后，关联页面缓存必须一并失效', async () => {
    const { saveStockinEdit, stockinEditForm } = useStockinEdit(async () => {}, confirmDialog)
    stockinEditForm.value = {
      id: 7, stockinNo: 'SI-1', productName: '测试产品', quantity: 3,
      customer: '测试客户', date: '2026-10-01', note: '',
    }

    await saveStockinEdit()

    expect(mocks.stockinEdit).toHaveBeenCalledWith(7, expect.objectContaining({ quantity: 3 }))
    expectCrossPageInvalidated('编辑备货')
  })

  it('删除备货（入库记录）后，关联页面缓存必须一并失效', async () => {
    const { handleDeleteStockin } = useStockinEdit(async () => {}, confirmDialog)

    await handleDeleteStockin({ id: 7, order_no: 'SI-1' } as never)

    expect(mocks.stockinDelete).toHaveBeenCalledWith(7)
    expectCrossPageInvalidated('删除备货')
  })
})
