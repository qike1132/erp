/**
 * BeileOrderTab 搜索防抖自动应用回归：
 *
 * BUG：/beile-order 页搜索框无查询按钮（HubeiView :show-actions="false"），
 * appliedProduct 仅在「点击下拉建议项」时更新；用户直接键入关键字
 * （如「变形金刚」）后列表完全不过滤 → 出现大量不相关结果。
 *
 * 修复：键入停顿 600ms 自动把输入文本确认为筛选值（appliedProduct），
 * 服务端 product 过滤 + 客户端 displayOrders 二次过滤同键生效。
 *
 * 测试通过宿主组件直接操作 provideBeileOrders 状态实例（filters.productKw），
 * 用 fake timers 推进防抖窗口，断言：
 * - 未停顿满 600ms 不应用（避免输入中途表格抖动）；
 * - 停顿满 600ms 自动应用 → displayOrders 仅保留命中行；
 * - 清空输入立即复位（与 HubeiSearchBar reset 事件殊途同归）。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref, defineComponent, h, nextTick } from 'vue'

const mocks = vi.hoisted(() => ({
  beileListMock: vi.fn(),
  queryData: null as unknown as ReturnType<typeof ref<unknown>>,
}))

vi.mock('@/api', () => ({
  orderApi: {
    beileList: mocks.beileListMock,
    confirmBeileOrder: vi.fn(),
    confirmBeileStockin: vi.fn(),
  },
}))

vi.mock('@tanstack/vue-query', async () => {
  const { ref: r } = await import('vue')
  const dataRef = r<unknown>(null)
  mocks.queryData = dataRef
  return {
    useQuery: () => ({ data: dataRef, isLoading: r(false), isFetching: r(false), refetch: vi.fn() }),
    useQueryClient: () => ({ setQueryData: vi.fn() }),
    keepPreviousData: {},
  }
})

vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }) }))

vi.mock('@/composables/useToast', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
  showToast: vi.fn(),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ hasPermission: () => true }),
}))

import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils'
import { provideBeileOrders } from '@/views/beile-order/composables/useBeileOrders'

enableAutoUnmount(afterEach)

function makeListResponse() {
  return {
    success: true,
    total: 2,
    page: 1,
    per_page: 18,
    unconfirmed_count: 0,
    data: [
      {
        id: 101,
        record_type: 'order',
        confirmed: false,
        confirmed_at: null,
        confirmed_by: null,
        order_no: 'PO-101',
        customer: '客户A',
        order_date: '2026-08-12',
        product_name: '变形金刚',
        product_id: 1,
        quantity: 10,
        deduct_quantity: 0,
        deduct_stock: false,
        note: '',
        status: '待备货',
        factories: ['湖北'],
        items: [{ id: 1, product_name: '变形金刚', product_barcode: '690001', quantity: 10, note: '' }],
      },
      {
        id: 102,
        record_type: 'order',
        confirmed: false,
        confirmed_at: null,
        confirmed_by: null,
        order_no: 'PO-102',
        customer: '客户B',
        order_date: '2026-08-11',
        product_name: '无关产品',
        product_id: 2,
        quantity: 30,
        deduct_quantity: 0,
        deduct_stock: false,
        note: '',
        status: '待备货',
        factories: ['湖北'],
        items: [{ id: 2, product_name: '无关产品', product_barcode: '690002', quantity: 30, note: '' }],
      },
    ],
  }
}

/** 宿主组件：创建并暴露 provideBeileOrders 状态实例（不经 HubeiSearchBar 直接驱动 filters） */
const DebounceHost = defineComponent({
  name: 'DebounceHost',
  setup(_, { expose }) {
    const bo = provideBeileOrders()
    expose({ bo })
    return () => h('div')
  },
})

async function mountHost() {
  const wrapper = mount(DebounceHost)
  await flushPromises()
  await nextTick()
  return wrapper
}

describe('beile-order 搜索：自由键入防抖自动应用（BUG-1）', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    mocks.queryData.value = makeListResponse()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('键入未停顿满 600ms 不应用筛选（避免输入中途表格抖动）', async () => {
    const wrapper = await mountHost()
    const bo = (wrapper.vm as unknown as { bo: { filters: { orderNo: string }; appliedProduct: { value: string } } }).bo
    bo.filters.productKw = '变形金刚'
    await flushPromises()
    vi.advanceTimersByTime(599)
    await nextTick()
    expect(bo.appliedProduct.value).toBe('')
  })

  it('键入「变形金刚」停顿 600ms 后自动应用 → 列表仅保留命中行', async () => {
    const wrapper = await mountHost()
    const bo = (wrapper.vm as unknown as {
      bo: {
        filters: { orderNo: string }
        appliedProduct: { value: string }
        displayOrders: { value: Array<{ id: number; product_name?: string }> }
      }
    }).bo
    bo.filters.productKw = '变形金刚'
    await flushPromises()
    vi.advanceTimersByTime(600)
    await nextTick()
    expect(bo.appliedProduct.value).toBe('变形金刚')
    // 客户端二次过滤：仅保留 product_name/items 命中关键字的行
    expect(bo.displayOrders.value.map((o) => o.id)).toEqual([101])
    expect(bo.displayOrders.value[0]!.product_name).toContain('变形金刚')
  })

  it('键入中途继续打字：防抖窗口重置，只在最终停顿后应用一次', async () => {
    const wrapper = await mountHost()
    const bo = (wrapper.vm as unknown as {
      bo: { filters: { orderNo: string }; appliedProduct: { value: string } }
    }).bo
    bo.filters.productKw = '变形'
    await flushPromises()
    vi.advanceTimersByTime(400)
    bo.filters.productKw = '变形金刚'
    await flushPromises()
    vi.advanceTimersByTime(400)
    expect(bo.appliedProduct.value).toBe('')
    vi.advanceTimersByTime(200)
    await nextTick()
    expect(bo.appliedProduct.value).toBe('变形金刚')
  })

  it('清空输入立即复位筛选值（与 HubeiSearchBar reset 事件殊途同归）', async () => {
    const wrapper = await mountHost()
    const bo = (wrapper.vm as unknown as {
      bo: { filters: { orderNo: string }; appliedProduct: { value: string } }
    }).bo
    bo.filters.productKw = '变形金刚'
    await flushPromises()
    vi.advanceTimersByTime(600)
    await nextTick()
    expect(bo.appliedProduct.value).toBe('变形金刚')
    bo.filters.productKw = ''
    await flushPromises()
    expect(bo.appliedProduct.value).toBe('')
  })
})
