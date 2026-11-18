/**
 * 移动端：路由切换取消的 GET 不得弹「加载失败」toast（2026-10-17 审计 P1-21 / 报告内 FE-MOBILE P1-1）。
 *
 * `request.ts` 的 `get()` 默认 `routeCancel = true`，请求被登记进 `_pendingControllers`；
 * `router/guards.ts` 的第一个 `beforeEach` 每次导航都调 `abortPendingRequests()`，把在途 GET
 * 一律 abort 成一个 `CanceledError`。这不是后端失败，是**我们主动取消的**。
 *
 * 三个视图的 catch 没有先判 `isCanceledError`，于是：
 *   - 把取消当业务失败，弹一条错误 toast；
 *   - `showToast` 容器挂在 document.body，**不随组件卸载消失** → 提示出现在用户刚跳到的
 *     新页面上（弱网下 MPurchaseView 一次 mount 并发 3 个请求，点返回会连弹 3 条）。
 * 同目录 MStockView / MProductView / MCaseView 早就是正确写法（catch 首行早退），
 * 这里是「同一条契约三处漏、三处对」的自相矛盾，维护者会误以为后端真挂了。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
  showToast: vi.fn(),
  purchaseOrders: vi.fn(),
  purchaseUnprocessed: vi.fn(),
  purchaseCompleted: vi.fn(),
  batchList: vi.fn(),
  orderList: vi.fn(),
}))

vi.mock('@/api', () => ({
  purchaseApi: {
    orders: mocks.purchaseOrders,
    unprocessedOrders: mocks.purchaseUnprocessed,
    completed: mocks.purchaseCompleted,
  },
  batchApi: { list: mocks.batchList },
  orderApi: { list: mocks.orderList },
}))

vi.mock('@/composables/useToast', () => ({
  showToast: mocks.showToast,
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
  useRoute: () => ({ query: {}, params: {} }),
}))

import MPurchaseView from '@/mobile/views/purchase/MPurchaseView.vue'
import MBatchView from '@/mobile/views/batch/MBatchView.vue'
import MCustomerOrderView from '@/mobile/views/customer-order/MCustomerOrderView.vue'

/** axios 在 abort 时 reject 的 CanceledError 形态（isCanceledError 认 code） */
const CANCELED = Object.assign(new Error('canceled'), { code: 'ERR_CANCELED' })

function stubs() {
  return {
    MobileNavBar: true,
    MFilterChips: true,
    MSearchBar: true,
    MList: true,
    MListItem: true,
    MEmpty: true,
    MSpinner: true,
    MBottomSheet: true,
  }
}

/** 只关心「加载/查询失败」类错误 toast，与无关提示解耦 */
function failureToastCalled(): boolean {
  return mocks.showToast.mock.calls.some(
    (call) => typeof call[0] === 'string' && call[0].includes('失败') && call[1] === 'error',
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.purchaseOrders.mockRejectedValue(CANCELED)
  mocks.purchaseUnprocessed.mockRejectedValue(CANCELED)
  mocks.purchaseCompleted.mockRejectedValue(CANCELED)
  mocks.batchList.mockRejectedValue(CANCELED)
  mocks.orderList.mockRejectedValue(CANCELED)
})

describe('P1-21 取消不是失败：三个移动端视图 catch 必须先早退', () => {
  it('MPurchaseView：三个列表请求被路由取消 → 不弹「加载失败」', async () => {
    const w = mount(MPurchaseView, { global: { stubs: stubs() } })
    const vm = w.vm as unknown as { refetchOrders: () => Promise<void> }
    await vm.refetchOrders()
    await flushPromises()

    expect(failureToastCalled()).toBe(false)
    w.unmount()
  })

  it('MBatchView：批次查询被路由取消 → 不弹「批次查询失败」', async () => {
    const w = mount(MBatchView, { global: { stubs: stubs() } })
    const vm = w.vm as unknown as { handleSearch: () => Promise<void> }
    await vm.handleSearch()
    await flushPromises()

    expect(failureToastCalled()).toBe(false)
    w.unmount()
  })

  it('MCustomerOrderView：订单查询被路由取消 → 不弹「订单查询失败」', async () => {
    const w = mount(MCustomerOrderView, { global: { stubs: stubs() } })
    const vm = w.vm as unknown as { handleSearch: () => Promise<void> }
    await vm.handleSearch()
    await flushPromises()

    expect(failureToastCalled()).toBe(false)
    w.unmount()
  })
})

describe('P1-21 防矫枉过正：真实后端失败仍然提示', () => {
  it('MBatchView：500 仍然弹「批次查询失败」并留下错误态', async () => {
    mocks.batchList.mockRejectedValue(Object.assign(new Error('boom'), { response: { status: 500 } }))
    const w = mount(MBatchView, { global: { stubs: stubs() } })
    const vm = w.vm as unknown as { handleSearch: () => Promise<void> }
    await vm.handleSearch()
    await flushPromises()

    expect(failureToastCalled()).toBe(true)
    w.unmount()
  })

  it('MCustomerOrderView：403 弹「没有订单查看权限」而不是笼统的查询失败', async () => {
    mocks.orderList.mockRejectedValue(Object.assign(new Error('forbidden'), { response: { status: 403 } }))
    const w = mount(MCustomerOrderView, { global: { stubs: stubs() } })
    const vm = w.vm as unknown as { handleSearch: () => Promise<void> }
    await vm.handleSearch()
    await flushPromises()

    expect(
      mocks.showToast.mock.calls.some(
        (call) => typeof call[0] === 'string' && call[0].includes('没有订单查看权限'),
      ),
    ).toBe(true)
    w.unmount()
  })
})
