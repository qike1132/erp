/**
 * 回归守卫：customer-order「暂存区 → 批量提交」的部分失败语义。
 *
 * 缺陷背景（2026-09-18）：`submitAll` 里「订单提交失败」会让备货分支被整体跳过
 * （守卫 `!orderFailed && stockinPayload.length`），但 `stockinFailed` 仍为 false，
 * 于是备货条目被从暂存区移除、并播报「备货已提交成功」——**从未提交的条目被当成提交成功**，
 * 用户既看不到数据、也失去了重试入口。
 *
 * 本文件锁死核心不变量：
 *   条目被移除  ⇔  该类请求确实发出过并且成功
 * 任何「播报成功但实际未提交」或「未提交却被移除」都会让断言失败。
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

const ORDERS_URL = '/aux/batch-submit-orders'
const STOCKINS_URL = '/aux/batch-submit-stockins'

function item(uid: string, type: 'order' | 'stockin'): StagedItem {
  return {
    uid,
    origin: 'manual',
    type,
    customer: '审计客户',
    productId: 101,
    productName: '审计产品',
    quantity: 3,
    date: '2026-09-18',
    note: '',
    deductStock: false,
    deductQuantity: 0,
    shipmentPlans: [],
  }
}

/** 让 orders 成功/失败、stockins 成功/失败可独立配置 */
function mockEndpoints(opts: { ordersOk: boolean; stockinsOk: boolean }) {
  mocks.postMock.mockImplementation((url: string) => {
    if (url === ORDERS_URL) {
      return opts.ordersOk
        ? Promise.resolve({ success: true, created_count: 1, results: [{ success: true, customer: '审计客户' }] })
        : Promise.reject(new Error('订单提交失败'))
    }
    if (url === STOCKINS_URL) {
      return opts.stockinsOk
        ? Promise.resolve({ success: true })
        : Promise.reject(new Error('备货提交失败'))
    }
    return Promise.reject(new Error(`unexpected url ${url}`))
  })
}

function toastTexts() {
  return vi.mocked(showToast).mock.calls.map((c) => String(c[0]))
}

function called(url: string) {
  return mocks.postMock.mock.calls.some((c) => c[0] === url)
}

/** useStagedItems 内部自建 stagedItems ref：必须用返回值播种，不能另建一个 */
function setup(items: StagedItem[]) {
  const api = useStagedItems()
  api.stagedItems.value = items
  return api
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('submitAll 部分失败语义', () => {
  it('订单失败 + 有备货：订单必须保留，且不得谎报订单成功', async () => {
    mockEndpoints({ ordersOk: false, stockinsOk: true })
    const { stagedItems, submitAll } = setup([item('o1', 'order'), item('s1', 'stockin'), item('s2', 'stockin')])

    await submitAll()

    const uids = stagedItems.value.map((i) => i.uid)
    // 核心断言 1：失败的一类必须留在暂存区，供用户重试
    expect(uids, '订单失败时应保留订单').toContain('o1')

    // 核心断言 2：备货的处置必须与它自身的真实结果一致（不允许"未提交却被移除"）
    const stockinsKept = ['s1', 's2'].every((id) => uids.includes(id))
    if (!stockinsKept) {
      expect(called(STOCKINS_URL), '备货被移出暂存区，但备货请求并未发出').toBe(true)
    }

    // 核心断言 3：不得出现任何声称「订单已提交成功」的文案。
    // 注意不能整串子串匹配——「提交失败：订单 1 条」里同时含"订单"和"已提交："，
    // 会假阳性。这里只解析「已提交：」之后、分号之前的那一段。
    const texts = toastTexts()
    const claimedDone = texts
      .flatMap((t) => (t.includes('已提交：') ? t.split('已提交：')[1]!.split('；')[0]! : []))
      .join('、')
    expect(
      claimedDone.includes('订单'),
      `不得谎报订单提交成功，已提交段=${JSON.stringify(claimedDone)}，全部播报=${JSON.stringify(texts)}`,
    ).toBe(false)
    expect(texts.some((t) => t.includes('已保留')), `应提示条目已保留：${JSON.stringify(texts)}`).toBe(true)
  })

  it('订单失败时，备货不得在未发出请求的情况下被移出暂存区（旧缺陷直击）', async () => {
    // 备货接口不可用：此时若备货仍从列表消失，就是把"未提交"当成了"已成功"
    mockEndpoints({ ordersOk: false, stockinsOk: false })
    const { stagedItems, submitAll } = setup([item('o1', 'order'), item('s1', 'stockin')])

    await submitAll()

    const uids = stagedItems.value.map((i) => i.uid)
    expect(uids, '订单失败').toContain('o1')
    expect(uids, '备货也未成功提交，必须保留').toContain('s1')
    expect(stagedItems.value, '暂存区不应被清空').toHaveLength(2)
  })

  it('订单失败时，备货请求要么真正发出并成功、要么条目保留 —— 二者不可矛盾', async () => {
    mockEndpoints({ ordersOk: false, stockinsOk: true })
    const { stagedItems, submitAll } = setup([item('o1', 'order'), item('s1', 'stockin')])

    await submitAll()

    const stockinRemoved = !stagedItems.value.some((i) => i.uid === 's1')
    // 不变量：移除 ⇔ 真的成功提交过
    expect(stockinRemoved, '备货被移除但请求未发出（或未成功）').toBe(called(STOCKINS_URL))
  })

  it('全部成功：两类条目都应被移除，并播报成功', async () => {
    mockEndpoints({ ordersOk: true, stockinsOk: true })
    const { stagedItems, submitAll } = setup([item('o1', 'order'), item('s1', 'stockin')])

    await submitAll()

    expect(stagedItems.value).toHaveLength(0)
    expect(called(ORDERS_URL)).toBe(true)
    expect(called(STOCKINS_URL)).toBe(true)
    expect(toastTexts().some((t) => t.includes('提交成功'))).toBe(true)
  })

  it('订单成功 + 备货失败：订单移除、备货保留', async () => {
    mockEndpoints({ ordersOk: true, stockinsOk: false })
    const { stagedItems, submitAll } = setup([item('o1', 'order'), item('s1', 'stockin')])

    await submitAll()

    const uids = stagedItems.value.map((i) => i.uid)
    expect(uids, '订单已成功，应移除').not.toContain('o1')
    expect(uids, '备货失败，应保留').toContain('s1')
    expect(toastTexts().some((t) => t.includes('已保留'))).toBe(true)
  })

  it('只有订单且失败：订单保留，不产生任何成功播报', async () => {
    mockEndpoints({ ordersOk: false, stockinsOk: true })
    const { stagedItems, submitAll } = setup([item('o1', 'order')])

    await submitAll()

    expect(stagedItems.value.map((i) => i.uid)).toContain('o1')
    expect(called(STOCKINS_URL), '没有备货条目时不应请求备货接口').toBe(false)
    expect(toastTexts().some((t) => t.startsWith('提交成功'))).toBe(false)
  })

  it('只有备货且成功：备货移除，不请求订单接口', async () => {
    mockEndpoints({ ordersOk: true, stockinsOk: true })
    const { stagedItems, submitAll } = setup([item('s1', 'stockin')])

    await submitAll()

    expect(stagedItems.value).toHaveLength(0)
    expect(called(ORDERS_URL), '没有订单条目时不应请求订单接口').toBe(false)
  })
  it('F-FE-DESK-CORE-03：部分分组失败——成功分组行移除，失败分组行保留并播报 warning', async () => {
    // 两个客户分组，B 组失败
    const a = item('oa1', 'order'); const b = item('ob1', 'order')
    b.customer = '失败客户'
    const { stagedItems, submitAll } = setup([a, b])
    mocks.postMock.mockImplementation((url: string) => {
      if (url === ORDERS_URL) {
        return Promise.resolve({
          success: true, created_count: 1,
          results: [
            { success: true, customer: '审计客户' },
            { success: false, customer: '失败客户', error: '产品不存在' },
          ],
        })
      }
      return Promise.reject(new Error(`unexpected url ${url}`))
    })
    await submitAll()
    expect(stagedItems.value.map((i) => i.uid)).toEqual(['ob1']) // 失败分组保留
    const texts = vi.mocked(showToast).mock.calls.map((c) => String(c[1]))
    expect(texts).toContain('warning')
  })

  it('F-FE-DESK-CORE-03：results 无 customer 字段（形状不符）——保守保留全部', async () => {
    const { stagedItems, submitAll } = setup([item('ox1', 'order')])
    mocks.postMock.mockImplementation((url: string) => {
      if (url === ORDERS_URL) {
        return Promise.resolve({ success: true, created_count: 1, results: [{ success: true }] })
      }
      return Promise.reject(new Error(`unexpected url ${url}`))
    })
    await submitAll()
    expect(stagedItems.value).toHaveLength(1) // 不清空
  })
})
