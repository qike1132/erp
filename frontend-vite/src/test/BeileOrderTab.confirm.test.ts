import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref, nextTick, defineComponent, h } from 'vue'

// Hoisted mock state — vi.mock factories are hoisted to the top of the file,
// so we keep mutable mocks inside vi.hoisted() and reference them by name.
const mocks = vi.hoisted(() => ({
  beileListMock: vi.fn(),
  confirmBeileOrderMock: vi.fn(),
  confirmBeileStockinMock: vi.fn(),
  refetchMock: vi.fn(),
  setQueryDataMock: vi.fn(),
  // 由 @tanstack/vue-query mock 工厂在导入时赋值为真实 ref（供测试内修改数据）
  queryData: null as unknown as ReturnType<typeof ref<unknown>>,
}))

vi.mock('@/api', () => ({
  orderApi: {
    beileList: mocks.beileListMock,
    confirmBeileOrder: mocks.confirmBeileOrderMock,
    confirmBeileStockin: mocks.confirmBeileStockinMock,
  },
}))

vi.mock('@/api/request', () => ({
  resolveStaticUrl: (url: string | null | undefined) => url ?? '',
}))

vi.mock('@tanstack/vue-query', async () => {
  const { ref } = await import('vue')
  const dataRef = ref<unknown>(null)
  mocks.queryData = dataRef
  return {
    useQuery: () => ({
      data: dataRef,
      isLoading: ref(false),
      isFetching: ref(false),
      refetch: mocks.refetchMock,
    }),
    useQueryClient: () => ({ setQueryData: mocks.setQueryDataMock }),
    keepPreviousData: {},
  }
})

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
}))

vi.mock('@/composables/useToast', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  },
  showToast: vi.fn(),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    hasPermission: () => true,
  }),
}))

import { mount, flushPromises } from '@vue/test-utils'
import BeileOrderTab from '@/views/beile-order/BeileOrderTab.vue'
import { provideBeileOrders, type BeileOrdersHandle } from '@/views/beile-order/composables/useBeileOrders'
import type { OrderListApiResponse } from '@/api/order'

// jsdom 中元素 clientHeight 恒为 0，导致 listAreaHeight=0、VirtualList 不渲染。
// 挂载前让所有元素报告一个非零高度，使列表主体（VirtualList）进入 v-if 分支。
Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
  configurable: true,
  get() {
    return 600
  },
})

// Stub child components that aren't relevant to the status column / confirm behavior.
// VirtualList must render every item through the default slot so rows appear in jsdom.
const stubs = {
  UiSpinner: { template: '<span class="ui-spinner-stub" />' },
  UiPagination: { template: '<div class="ui-pagination-stub" />' },
  UiButton: { template: '<button type="button"><slot /></button>' },
  UiDialog: {
    props: ['open', 'title', 'maxWidthClass'],
    template: '<div v-if="open" class="ui-dialog-stub"><slot /><slot name="footer" /></div>',
  },
  VirtualList: {
    props: ['items'],
    methods: {
      scrollToTop() {},
    },
    template: '<div class="vl-stub"><div v-for="item in items" :key="item.id" class="vl-row"><slot :item="item" /></div></div>',
  },
}

/** 构造 beile-list 响应（未确认筛选视角，含一个未确认订单 + 一个已确认订单 + 一条备货记录） */
function makeListResponse(overrides: Partial<OrderListApiResponse> = {}): OrderListApiResponse {
  return {
    success: true,
    total: 3,
    page: 1,
    per_page: 18,
    unconfirmed_count: 1,
    data: [
      {
        id: 101,
        record_type: 'order',
        confirmed: false,
        confirmed_at: null,
        confirmed_by: null,
        order_no: 'PO-101',
        customer: '未确认客户',
        order_date: '2026-08-12',
        product_name: '产品A',
        product_id: 1,
        quantity: 10,
        deduct_quantity: 0,
        deduct_stock: false,
        note: '',
        status: '待备货',
        factories: ['湖北'],
        items: [{ id: 1, product_name: '产品A', quantity: 10 }],
      },
      {
        id: 102,
        record_type: 'order',
        confirmed: true,
        confirmed_at: '2026-08-12T10:00:00',
        confirmed_by: 'admin',
        order_no: 'PO-102',
        customer: '已确认客户',
        order_date: '2026-08-11',
        product_name: '产品B',
        product_id: 2,
        quantity: 5,
        deduct_quantity: 0,
        deduct_stock: false,
        note: '',
        status: '待备货',
        factories: ['湖北'],
        items: [{ id: 2, product_name: '产品B', quantity: 5 }],
      },
      {
        id: 201,
        record_type: 'stockin',
        confirmed: true,
        confirmed_at: '2026-08-10 08:00:00',
        confirmed_by: 'admin',
        customer: '备货客户',
        order_date: '2026-08-10',
        product_name: '产品C',
        product_id: 3,
        quantity: 3,
        deduct_quantity: 0,
        deduct_stock: false,
        note: '',
        status: '已入库',
        factories: ['湖北'],
        items: [],
      },
    ],
    ...overrides,
  } as OrderListApiResponse
}

/** 测试包装组件：在 setup 中调用 provideBeileOrders 创建状态实例并 provide 给 BeileOrderTab */
let boHandle: BeileOrdersHandle
const TestHost = defineComponent({
  setup() {
    boHandle = provideBeileOrders()
    return () => h(BeileOrderTab)
  },
})

/** 挂载组件并等待初始查询渲染 */
async function mountTab() {
  const wrapper = mount(TestHost, { global: { stubs } })
  await flushPromises()
  await nextTick()
  return wrapper
}

describe('BeileOrderTab 状态列与确认按钮行为', () => {
  beforeEach(() => {
    mocks.beileListMock.mockReset()
    mocks.confirmBeileOrderMock.mockReset()
    mocks.confirmBeileStockinMock.mockReset()
    mocks.refetchMock.mockReset()
    mocks.setQueryDataMock.mockReset()
    // setQueryData 真实应用 updater，让乐观移除可以在 DOM 上观察到
    mocks.setQueryDataMock.mockImplementation((_key: unknown, updater: unknown) => {
      if (typeof updater === 'function' && mocks.queryData) {
        mocks.queryData.value = updater(mocks.queryData.value)
      }
    })
    mocks.queryData.value = makeListResponse()
    mocks.confirmBeileOrderMock.mockResolvedValue({ success: true, message: '订单已确认' })
    mocks.confirmBeileStockinMock.mockResolvedValue({ success: true, message: '备货已确认' })
  })

  it('状态列：未确认记录显示「未确认」徽章，已确认订单/备货显示「已确认」徽章', async () => {
    const wrapper = await mountTab()

    // 切换到「已确认」状态（确认状态 TAB 已迁至 HubeiView 头部，此处直接调用暴露方法）
    ;boHandle.setConfirmStatus('confirmed')
    await nextTick()

    const rows = wrapper.findAll('.vl-row')
    expect(rows.length).toBe(3)

    // 已确认 TAB 下确认操作列隐藏，徽章仅出现在状态列：未确认订单 + 已确认订单/备货
    const pendingBadges = wrapper.findAll('.bo-confirm-badge--pending')
    expect(pendingBadges.length).toBe(1)
    expect(pendingBadges[0]!.text()).toBe('未确认')

    const doneBadges = wrapper.findAll('.bo-confirm-badge--done')
    expect(doneBadges.length).toBe(2)
    expect(doneBadges.every((b) => b.text() === '已确认')).toBe(true)

    // 备货记录状态列显示「已确认」徽章
    const stockinRow = rows[2]!
    expect(stockinRow.findAll('.bo-confirm-badge--done').length).toBe(1)
  })

  it('确认列：未确认订单仅显示「确认订单」按钮（无「未确认订单」标签），已确认订单无按钮', async () => {
    const wrapper = await mountTab()
    ;boHandle.setConfirmStatus('unconfirmed')
    await nextTick()

    const rows = wrapper.findAll('.vl-row')

    // 未确认订单：确认列只有按钮，没有「未确认订单」标签
    const unconfirmedRow = rows[0]!
    const btn = unconfirmedRow.find('.bo-confirm-btn')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).toBe('确认订单')
    // 未确认 TAB 下「确认状态」列已隐藏，行内不应出现 pending 徽章
    const pendingBadges = unconfirmedRow.findAll('.bo-confirm-badge--pending')
    expect(pendingBadges.length).toBe(0)

    // 已确认订单：确认列无按钮，仅一个 done 徽章（确认操作列）
    const confirmedRow = rows[1]!
    expect(confirmedRow.find('.bo-confirm-btn').exists()).toBe(false)
    expect(confirmedRow.findAll('.bo-confirm-badge--done').length).toBe(1)

    // 已确认备货记录：无按钮
    expect(rows[2]!.find('.bo-confirm-btn').exists()).toBe(false)
  })

  it('点击「确认订单」调用 confirmBeileOrder、提示成功，并在未确认筛选下乐观移除该行', async () => {
    const wrapper = await mountTab()
    ;boHandle.setConfirmStatus('unconfirmed')
    await nextTick()
    const btn = wrapper.find('.vl-row .bo-confirm-btn')
    expect(btn.exists()).toBe(true)

    await btn.trigger('click')
    await flushPromises()
    await nextTick()

    // 调用了确认接口（订单 id）
    expect(mocks.confirmBeileOrderMock).toHaveBeenCalledTimes(1)
    expect(mocks.confirmBeileOrderMock).toHaveBeenCalledWith(101)

    // 成功 toast
    const { toast } = await import('@/composables/useToast')
    expect(toast.success).toHaveBeenCalledWith('订单已确认')

    // 未确认筛选下：行被乐观移除，剩余 2 行（已确认订单 + 备货记录）
    const rows = wrapper.findAll('.vl-row')
    expect(rows.length).toBe(2)
    expect(rows.map((r) => r.text())).not.toContain(expect.stringContaining('未确认客户'))
  })

  it('未确认备货显示「确认备货」按钮，点击调用 confirmBeileStockin、提示成功并乐观移除', async () => {
    // 列表仅含一条未确认备货记录
    mocks.queryData.value = makeListResponse({
      total: 1,
      unconfirmed_count: 1,
      data: [
        {
          id: 201,
          record_type: 'stockin',
          confirmed: false,
          confirmed_at: null,
          confirmed_by: null,
          customer: '备货客户',
          order_date: '2026-08-10',
          product_name: '产品C',
          product_id: 3,
          quantity: 3,
          deduct_quantity: 0,
          deduct_stock: false,
          note: '',
          status: '已入库',
          factories: ['湖北'],
          items: [],
        },
      ] as unknown as OrderListApiResponse['data'],
    })

    const wrapper = await mountTab()
    ;boHandle.setConfirmStatus('unconfirmed')
    await nextTick()

    const btn = wrapper.find('.vl-row .bo-confirm-btn')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).toBe('确认订单')

    await btn.trigger('click')
    await flushPromises()
    await nextTick()

    // 调用备货确认接口（而非订单确认接口）
    expect(mocks.confirmBeileStockinMock).toHaveBeenCalledTimes(1)
    expect(mocks.confirmBeileStockinMock).toHaveBeenCalledWith(201)
    expect(mocks.confirmBeileOrderMock).not.toHaveBeenCalled()

    const { toast } = await import('@/composables/useToast')
    expect(toast.success).toHaveBeenCalledWith('备货已确认')

    // 未确认筛选下：行被乐观移除
    expect(wrapper.findAll('.vl-row').length).toBe(0)
  })

  it('确认中：按钮禁用并显示「确认中…」，请求完成后恢复', async () => {
    // 挂起确认请求
    let resolveConfirm!: (v: { success: boolean; message: string }) => void
    mocks.confirmBeileOrderMock.mockImplementation(
      () => new Promise<{ success: boolean; message: string }>((resolve) => { resolveConfirm = resolve }),
    )

    const wrapper = await mountTab()
    ;boHandle.setConfirmStatus('unconfirmed')
    await nextTick()
    const btn = wrapper.find('.vl-row .bo-confirm-btn')

    await btn.trigger('click')
    await nextTick()

    // 请求未返回前：禁用 + 文案
    const disabledBtn = wrapper.find('.bo-confirm-btn')
    expect((disabledBtn.element as HTMLButtonElement).disabled).toBe(true)
    expect(disabledBtn.text()).toBe('确认中…')

    // 完成后：默认「未确认」筛选下该行被乐观移除，列表回到 2 行，确认按钮不再存在
    resolveConfirm({ success: true, message: '订单已确认' })
    await flushPromises()
    await nextTick()

    expect(wrapper.findAll('.vl-row').length).toBe(2)
    expect(wrapper.find('.bo-confirm-btn').exists()).toBe(false)
  })

  it('已确认订单不显示确认按钮，因此不存在误触发确认的场景', async () => {
    const wrapper = await mountTab()
    ;boHandle.setConfirmStatus('unconfirmed')
    await nextTick()
    // 已确认订单行（第 2 行）内没有任何 .bo-confirm-btn
    const confirmedRow = wrapper.findAll('.vl-row')[1]!
    expect(confirmedRow.find('.bo-confirm-btn').exists()).toBe(false)
    // 全表只有一个确认按钮（仅未确认订单）
    expect(wrapper.findAll('.bo-confirm-btn').length).toBe(1)
  })

  it('默认 TAB 为「未确认」：初始 confirmStatus 为 unconfirmed（「全部」TAB 已移除）', async () => {
    const wrapper = await mountTab()

    // 默认确认状态为未确认
    expect(boHandle.confirmStatus.value).toBe('unconfirmed')

    // 未确认 TAB 下：行内显示「确认订单」按钮，不显示确认状态徽章
    const row = wrapper.findAll('.vl-row')[0]!
    expect(row.find('.bo-confirm-btn').exists()).toBe(true)
    expect(row.find('.bo-confirm-badge').exists()).toBe(false)
  })

  it('未下单订单：确认按钮禁用，且点击被前端门控拦截（不调接口 + 提示）', async () => {
    mocks.queryData.value = makeListResponse({
      total: 1,
      unconfirmed_count: 1,
      data: [
        {
          id: 101,
          record_type: 'order',
          confirmed: false,
          confirmed_at: null,
          confirmed_by: null,
          order_no: 'PO-101',
          customer: '未下单客户',
          order_date: '2026-08-12',
          product_name: '产品A',
          product_id: 1,
          quantity: 10,
          deduct_quantity: 0,
          deduct_stock: false,
          note: '',
          status: '待备货',
          factories: ['湖北'],
          items: [{ id: 1, product_name: '产品A', quantity: 10 }],
          is_ordered: false,
          purchase_order_qty: 0,
          spare_quantity: 0,
        },
      ] as unknown as OrderListApiResponse['data'],
    })

    const wrapper = await mountTab()
    ;boHandle.setConfirmStatus('unconfirmed')
    await nextTick()

    const btn = wrapper.find('.vl-row .bo-confirm-btn')
    expect(btn.exists()).toBe(true)
    // 按钮禁用（disabled 属性 + 文案/tooltip）
    expect((btn.element as HTMLButtonElement).disabled).toBe(true)
    expect(btn.attributes('title')).toBe('请先在采购中心完成下单')

    // 点击禁用按钮不触发任何确认（disabled 元素在 jsdom 下不派发 click）
    await btn.trigger('click')
    await flushPromises()
    expect(mocks.confirmBeileOrderMock).not.toHaveBeenCalled()

    // 直接调用底层 handler，证明 composable 级门控：不发请求 + toast 提示
    const item = boHandle.orders.value[0]!
    expect(item.is_ordered).toBe(false)
    await boHandle.handleConfirm(item)
    await flushPromises()
    expect(mocks.confirmBeileOrderMock).not.toHaveBeenCalled()
    const { toast } = await import('@/composables/useToast')
    expect(toast.error).toHaveBeenCalledWith('请先在采购中心完成下单')
  })

  it('已下单订单：数量列显示实际下单数量、「小义开单」列显示「已开单」、生产数量 = 订单数量+备品数量（备品独立列已删除）', async () => {
    mocks.queryData.value = makeListResponse({
      total: 1,
      unconfirmed_count: 1,
      data: [
        {
          id: 101,
          record_type: 'order',
          confirmed: false,
          confirmed_at: null,
          confirmed_by: null,
          order_no: 'PO-101',
          customer: '已下单客户',
          order_date: '2026-08-12',
          product_name: '产品A',
          product_id: 1,
          quantity: 10,
          deduct_quantity: 0,
          deduct_stock: false,
          note: '',
          status: '待备货',
          factories: ['湖北'],
          items: [{ id: 1, product_name: '产品A', quantity: 10 }],
          is_ordered: true,
          purchase_order_qty: 8,
          spare_quantity: 2,
          spare_rate: 5,
        },
      ] as unknown as OrderListApiResponse['data'],
    })

    const wrapper = await mountTab()
    ;boHandle.setConfirmStatus('unconfirmed')
    await nextTick()

    const row = wrapper.findAll('.vl-row')[0]!
    // 数量列：加粗显示实际下单数量 8（而非客户订单原数量 10）
    const orderedQty = row.find('.bo-qty--ordered')
    expect(orderedQty.exists()).toBe(true)
    expect(orderedQty.text()).toBe('8')
    // 生产数量：显示 订单数量 + 备品数量 = 8 + 2 = 10（备品独立列已删除）
    expect(row.find('.bo-prod').text()).toBe('10')
    // 「小义开单」列：is_ordered=true → 成功态「已开单」，无警示态
    const openBadge = row.find('.bo-open-badge--done')
    expect(openBadge.exists()).toBe(true)
    expect(openBadge.text()).toBe('已开单')
    expect(row.find('.bo-open-badge--pending').exists()).toBe(false)
    // 确认按钮可用
    const btn = row.find('.bo-confirm-btn')
    expect(btn.exists()).toBe(true)
    expect((btn.element as HTMLButtonElement).disabled).toBe(false)
  })

  it('已确认的历史行（已确认 + 未下单，CR-1）：小义开单仅中性灰「未开单」（无警示色/无 tooltip）、数量走原口径、无确认按钮', async () => {
    mocks.queryData.value = makeListResponse({
      total: 1,
      unconfirmed_count: 0,
      data: [
        {
          id: 101,
          record_type: 'order',
          confirmed: true,
          confirmed_at: '2026-08-12T10:00:00',
          confirmed_by: 'admin',
          order_no: 'PO-101',
          customer: '历史客户',
          order_date: '2026-08-12',
          product_name: '产品A',
          product_id: 1,
          quantity: 10,
          deduct_quantity: 0,
          deduct_stock: false,
          note: '',
          status: '待备货',
          factories: ['湖北'],
          items: [{ id: 1, product_name: '产品A', quantity: 10 }],
          is_ordered: false,
          purchase_order_qty: 10,
          spare_quantity: 0,
        },
      ] as unknown as OrderListApiResponse['data'],
    })

    const wrapper = await mountTab()
    ;boHandle.setConfirmStatus('confirmed')
    await nextTick()

    const row = wrapper.findAll('.vl-row')[0]!
    // 数量：原数量 10（订单级汇总），且已去徽章
    const qtyCell = row.find('.bo-qty')
    expect(qtyCell.text()).toBe('10')
    expect(qtyCell.classes()).not.toContain('bo-qty--ordered')
    // CR-1 守卫：已确认历史行不得出现警示态「未开单」，只用中性灰（不制造红色噪音）
    expect(row.find('.bo-open-badge--pending').exists()).toBe(false)
    expect(row.find('.bo-open-badge--done').exists()).toBe(false)
    const muted = row.find('.bo-open-badge--muted')
    expect(muted.exists()).toBe(true)
    expect(muted.text()).toBe('未开单')
    expect(muted.attributes('title')).toBeUndefined()
    // 已确认：确认状态列显示「已确认」徽章
    expect(row.find('.bo-confirm-badge--done').exists()).toBe(true)
    // 已确认 TAB 下确认操作列隐藏；即便在未确认 TAB 也因 confirmed=true 走「已确认」分支，无按钮
    expect(row.find('.bo-confirm-btn').exists()).toBe(false)
  })
})
