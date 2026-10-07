/**
 * 回归守卫：备货批量提交的**逐条**失败语义（2026-10-07 迭代审核修复）。
 *
 * 缺陷背景：`batch_create_stockins` 恒返回 HTTP 200，逐条以 `{success:false}` 表达失败。
 * 原实现把「请求未抛异常」当作整批成功，于是：
 *   1) 播报按暂存全量报「备货入库 N 条（库存 +Q）」，把失败行也算进去；
 *   2) `dropUids(stockinUids)` 把**失败行一并移出暂存区** → 用户既看不到、也无法重试。
 *
 * 另修一处时序问题：播报件数原先在 `await` 之后从**活的**暂存区现算，而提交在途期间
 * 表单仍可新增条目 → 播报件数与实际入库不符。
 *
 * 本文件锁死：
 *   备货条目被移除  ⇔  该条在响应 results 中 success === true
 *   播报的条数/件数 ⇔  实际提交那一批中的成功者（不受在途增删影响）
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'

const mocks = vi.hoisted(() => ({
  postMock: vi.fn(),
}))

vi.mock('@/api/request', () => ({
  get: vi.fn(),
  post: mocks.postMock,
  put: vi.fn(),
  del: vi.fn(),
  upload: mocks.postMock,
  download: vi.fn(),
}))

vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))
vi.mock('@tanstack/vue-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
  useQuery: () => ({ data: ref(undefined) }),
}))
vi.mock('@/composables/useConfirmDialog', () => ({
  useConfirmDialog: () => ({
    open: false, text: '', sub: '', type: 'warning',
    onConfirm: vi.fn(), onCancel: vi.fn(), confirm: vi.fn(async () => true),
  }),
}))

import { showToast } from '@/composables/useToast'
import { useStagedItems } from '@/views/customer-order/composables/useStagedItems'
import type { StagedItem } from '@/views/customer-order/composables/types'

function stockin(uid: string, quantity: number): StagedItem {
  return {
    uid,
    origin: 'manual',
    type: 'stockin',
    customer: '审计客户',
    productId: 101,
    productName: '审计产品',
    quantity,
    date: '2026-10-07',
    note: '',
    deductStock: false,
    deductQuantity: 0,
    shipmentPlans: [],
  } as StagedItem
}

/** 取最后一次 toast 的文案 */
function lastToast(): string {
  const calls = vi.mocked(showToast).mock.calls
  return String(calls[calls.length - 1]?.[0] ?? '')
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('备货逐条失败', () => {
  it('部分失败：只播报成功者，失败行保留可重试', async () => {
    mocks.postMock.mockResolvedValue({
      success: true,
      results: [{ success: false, error: '产品不存在' }, { success: true }],
    })
    const api = useStagedItems()
    api.stagedItems.value = [stockin('a', 3), stockin('b', 7)]

    await api.submitAll()

    expect(lastToast()).toContain('备货入库 1 条（库存 +7）')
    expect(lastToast()).toContain('1 条未入库')
    // 失败的那条必须留在暂存区（quantity 3），成功的那条移除
    expect(api.stagedItems.value.map((i) => i.uid)).toEqual(['a'])
  })

  it('全部失败：不报「库存 +N」，两条都保留', async () => {
    mocks.postMock.mockResolvedValue({
      success: true,
      results: [{ success: false, error: 'x' }, { success: false, error: 'y' }],
    })
    const api = useStagedItems()
    api.stagedItems.value = [stockin('a', 3), stockin('b', 7)]

    await api.submitAll()

    expect(lastToast()).not.toContain('库存 +')
    expect(api.stagedItems.value.map((i) => i.uid)).toEqual(['a', 'b'])
  })

  it('响应缺 results 时退回整批移除（避免重复入库）', async () => {
    mocks.postMock.mockResolvedValue({ success: true })
    const api = useStagedItems()
    api.stagedItems.value = [stockin('a', 3), stockin('b', 7)]

    await api.submitAll()

    expect(lastToast()).toContain('备货入库 2 条（库存 +10）')
    expect(api.stagedItems.value).toHaveLength(0)
  })

  it('提交在途期间新增的备货不计入播报、也不被移除', async () => {
    let release: (v: unknown) => void = () => {}
    mocks.postMock.mockImplementation(
      () => new Promise((resolve) => { release = resolve }),
    )
    const api = useStagedItems()
    api.stagedItems.value = [stockin('a', 3)]

    const inFlight = api.submitAll()
    // 等请求真的发出后再动暂存区——否则 release 落在 mock 被调用之前，promise 无人 resolve
    await vi.waitFor(() => expect(mocks.postMock).toHaveBeenCalledTimes(1))
    // 请求在途：用户又加了一条 5 件
    api.stagedItems.value = [...api.stagedItems.value, stockin('b', 5)]
    release({ success: true, results: [{ success: true }] })
    await inFlight

    // 播报只反映实际提交的那批（3 件），新增的 b 留在暂存区
    expect(lastToast()).toContain('库存 +3')
    expect(api.stagedItems.value.map((i) => i.uid)).toEqual(['b'])
  })
})
