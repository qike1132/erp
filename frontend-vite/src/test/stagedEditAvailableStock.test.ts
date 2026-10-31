/**
 * useStagedEdit —— 可用备货的请求序号与保存前校验（2026-10-30 审计 A-M36）
 *
 * 现场：暂存条目编辑弹窗里的「可用备货」决定用户填多少抵扣量。
 *   1) 连续打开不同条目时先发的查询可能后到，把 A 产品的可用量写到 B 产品的
 *      弹窗上 —— 用户照着这个数字填，后端按 B 的备货扣，结果「少扣且无提示」；
 *   2) 后端 `min(请求, 可用)` 是静默截断：填 10 实际只扣 6 也不报错。
 * 因此这里锁两件事：只接受最后一次查询的结果；保存前按已确认的可用量校验。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'

const mocks = vi.hoisted(() => ({
  availableStockinsMock: vi.fn(),
  showToastMock: vi.fn(),
}))

vi.mock('@/api', () => ({
  auxApi: { availableStockins: mocks.availableStockinsMock },
}))

vi.mock('@/composables/useToast', () => ({
  showToast: mocks.showToastMock,
}))

import { useStagedEdit } from '@/views/customer-order/composables/useStagedEdit'
import type { StagedItem, AvailableStockinItem } from '@/views/customer-order/composables/types'

function staged(over: Partial<StagedItem> = {}): StagedItem {
  return {
    uid: 'u1',
    type: 'order',
    customer: '贝乐',
    productId: 1,
    productName: '产品A',
    quantity: 10,
    date: '2026-10-30',
    note: '',
    deductStock: false,
    deductQuantity: 0,
    shipmentPlans: [],
    ...over,
  }
}

function deferred<T>() {
  let resolve!: (v: T) => void
  let reject!: (e: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

/** 让已 resolve 的 promise 的 then/catch 回调跑完 */
async function flush() {
  await Promise.resolve()
  await Promise.resolve()
}

describe('useStagedEdit 可用备货：请求序号', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('同一条目被重复打开时，先发的查询后到不得覆盖后发的可用量', async () => {
    const first = deferred<AvailableStockinItem[]>()
    const second = deferred<AvailableStockinItem[]>()
    mocks.availableStockinsMock
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise)

    const items = ref<StagedItem[]>([staged({ uid: 'a' })])
    const hook = useStagedEdit(items)

    hook.openEditStaged('a')
    hook.openEditStaged('a')

    second.resolve([{ id: 1, quantity: 5, deducted: 0, available: 5 }])
    await second.promise
    first.resolve([{ id: 1, quantity: 99, deducted: 0, available: 99 }])
    await first.promise
    await flush()

    // 无序号守卫时，后到的旧响应会把 99 写回（同一产品，产品比对栏拦不住）
    expect(hook.editAvailableStock.value).toBe(5)
    expect(hook.editStockState.value).toBe('ready')
  })

  it('切换到另一条目后，前一条目的响应被丢弃（产品/客户比对兜底）', async () => {
    const first = deferred<AvailableStockinItem[]>()
    const second = deferred<AvailableStockinItem[]>()
    mocks.availableStockinsMock
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise)

    const items = ref<StagedItem[]>([
      staged({ uid: 'a', productId: 1 }),
      staged({ uid: 'b', productId: 2, productName: '产品B' }),
    ])
    const hook = useStagedEdit(items)

    hook.openEditStaged('a')
    hook.openEditStaged('b')

    second.resolve([{ id: 2, quantity: 4, deducted: 0, available: 4 }])
    await second.promise
    first.resolve([{ id: 1, quantity: 70, deducted: 0, available: 70 }])
    await first.promise
    await flush()

    expect(hook.editAvailableStock.value).toBe(4)
    expect(hook.editStagedData.value?.productId).toBe(2)
  })

  it('打开新条目先清零可用量，别让上一条的数字停留在新弹窗里', () => {
    mocks.availableStockinsMock.mockReturnValue(new Promise(() => {}))
    const items = ref<StagedItem[]>([
      staged({ uid: 'a', productId: 1 }),
      staged({ uid: 'b', productId: 2 }),
    ])
    const hook = useStagedEdit(items)

    hook.openEditStaged('a')
    hook.openEditStaged('b')

    expect(hook.editAvailableStock.value).toBe(0)
    expect(hook.editStockState.value).toBe('loading')
  })
})

describe('useStagedEdit 可用备货：保存前校验', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('抵扣数量超过已确认的可用备货 → 保存被拦，暂存条目不被改写', async () => {
    mocks.availableStockinsMock.mockResolvedValue([
      { id: 1, quantity: 4, deducted: 0, available: 4 },
    ])
    const items = ref<StagedItem[]>([staged({ uid: 'a', deductStock: true })])
    const hook = useStagedEdit(items)

    hook.openEditStaged('a')
    await flush()
    expect(hook.editStockState.value).toBe('ready')

    hook.editStagedData.value!.deductQuantity = 6
    hook.saveEditStaged()

    // 后端 min(6, 4) 会安静地只扣 4：拦住并给出两边数字
    expect(mocks.showToastMock).toHaveBeenCalledWith(
      expect.stringContaining('超过当前可用备货 4'),
      'warning',
    )
    expect(items.value[0]!.deductQuantity).toBe(0)
    expect(hook.editStagedVisible.value).toBe(true)
  })

  it('可用备货查询失败 → 无法校验，保存同样被拦（不拿 0 当业务事实）', async () => {
    mocks.availableStockinsMock.mockRejectedValue(new Error('boom'))
    const items = ref<StagedItem[]>([staged({ uid: 'a', deductStock: true })])
    const hook = useStagedEdit(items)

    hook.openEditStaged('a')
    await flush()
    expect(hook.editStockState.value).toBe('error')

    hook.editStagedData.value!.deductQuantity = 3
    hook.saveEditStaged()

    expect(mocks.showToastMock).toHaveBeenCalledWith(
      expect.stringContaining('可用备货查询失败'),
      'warning',
    )
    expect(items.value[0]!.deductQuantity).toBe(0)
  })

  it('抵扣数量在可用范围内 → 正常保存', async () => {
    mocks.availableStockinsMock.mockResolvedValue([
      { id: 1, quantity: 8, deducted: 0, available: 8 },
    ])
    const items = ref<StagedItem[]>([staged({ uid: 'a', deductStock: true })])
    const hook = useStagedEdit(items)

    hook.openEditStaged('a')
    await flush()

    hook.editStagedData.value!.deductQuantity = 6
    hook.saveEditStaged()

    expect(mocks.showToastMock).not.toHaveBeenCalled()
    expect(items.value[0]!.deductQuantity).toBe(6)
    expect(items.value[0]!.deductStock).toBe(true)
    expect(hook.editStagedVisible.value).toBe(false)
  })

  it('不抵扣的条目不受可用备货影响，也不发查询', async () => {
    const items = ref<StagedItem[]>([
      staged({ uid: 'a', productId: 0, deductQuantity: 0 }),
    ])
    const hook = useStagedEdit(items)

    hook.openEditStaged('a')
    await flush()

    expect(mocks.availableStockinsMock).not.toHaveBeenCalled()
    expect(hook.editStockState.value).toBe('idle')

    hook.saveEditStaged()
    expect(mocks.showToastMock).not.toHaveBeenCalled()
    expect(hook.editStagedVisible.value).toBe(false)
  })
})
