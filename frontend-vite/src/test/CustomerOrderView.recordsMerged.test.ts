import { describe, it, expect, vi, beforeEach } from 'vitest'

// Hoisted mock state — vi.mock factories are hoisted to the top of the file,
// so we keep mutable mocks inside vi.hoisted() and reference them by name.
const mocks = vi.hoisted(() => ({
  recordsMock: vi.fn(),
  orderDetailMock: vi.fn(),
  customerActiveNamesMock: vi.fn(),
}))

vi.mock('@/api', () => ({
  orderApi: {
    records: mocks.recordsMock,
    detail: mocks.orderDetailMock,
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    lock: vi.fn(),
    unlock: vi.fn(),
    deductStock: vi.fn(),
    updateDeduct: vi.fn(),
    staging: {
      add: vi.fn(),
      list: vi.fn(),
      delete: vi.fn(),
      confirm: vi.fn(),
    },
  },
  customerApi: {
    activeNames: mocks.customerActiveNamesMock,
  },
}))

vi.mock('@/api/request', () => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  del: vi.fn(),
}))

vi.mock('@tanstack/vue-query', () => ({
  useQuery: () => ({ data: { value: { names: [] } } }),
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))

vi.mock('@/composables/useToast', () => ({
  showToast: vi.fn(),
}))

vi.mock('@/composables/useConfirmDialog', () => ({
  useConfirmDialog: () => ({
    open: false,
    text: '',
    sub: '',
    type: 'warning',
    onConfirm: vi.fn(),
    onCancel: vi.fn(),
    confirm: vi.fn(async () => true),
  }),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    user: { factory: '' },
    loaded: true,
    hasPermission: vi.fn(() => true),
  }),
}))

import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import CustomerOrderView from '@/views/customer-order/CustomerOrderView.vue'

const stubs = {
  UiInput: { template: '<input />' },
  UiDatePicker: { template: '<input />' },
  UiButton: { template: '<button><slot /></button>' },
  UiDialog: {
    template: '<div v-if="open" class="ui-dialog-stub"><slot /><slot name="footer" /></div>',
    props: ['open', 'title', 'maxWidthClass'],
  },
  UiSelect: { template: '<div class="ui-select-stub" />' },
  UiPagination: { template: '<div />' },
  UiConfirmDialog: { template: '<div />' },
  UiAutocomplete: { template: '<input />' },
}

/** 切到「记录查询」页签（activeTab watch 触发 fetchOrders） */
async function switchToRecordsTab(wrapper: ReturnType<typeof mount>) {
  const recordsTab = wrapper.findAll('button.co-tab-btn').find((b) => b.text().includes('记录查询'))
  expect(recordsTab, '记录查询 tab button should exist').toBeTruthy()
  await recordsTab!.trigger('click')
  await flushPromises()
  await nextTick()
}

/** 合并记录的统一 mock 数据：1 订单行 + 1 备货行 */
function mergedRecordsResponse() {
  return {
    success: true,
    data: [
      {
        id: 1,
        record_type: 'order',
        order_no: 'DD-100',
        customer: '客户A',
        order_date: '2026-09-30 09:12',
        status: '待备货',
        product: { id: 1, name: '断桥铝窗框', barcode: '6901', image: '' },
        quantity: 120,
        deduct_quantity: 40,
        factories: ['东莞'],
        items: [
          { id: 1, product_name: 'SKU1', quantity: 4 },
          { id: 2, product_name: 'SKU2', quantity: 3 },
        ],
      },
      {
        id: 2,
        record_type: 'stockin',
        order_no: 'BH-200',
        customer: '客户B',
        order_date: '2026-09-30 09:05',
        status: null,
        product: { id: 2, name: '不锈钢合页', barcode: '6902', image: '' },
        quantity: 500,
        deduct_quantity: 0,
        factories: ['东莞'],
        items: [{ id: 2, product_name: '不锈钢合页', quantity: 500 }],
      },
    ],
    total: 2,
    page: 1,
    per_page: 20,
  }
}

describe('CustomerOrderView 记录列表合并 + 搜索栏（F2）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mocks.recordsMock.mockReset()
    mocks.orderDetailMock.mockReset()
    mocks.customerActiveNamesMock.mockReset()
    mocks.customerActiveNamesMock.mockResolvedValue({ names: [] })
    mocks.recordsMock.mockResolvedValue(mergedRecordsResponse())
  })

  it('订单与备货行在同一张表中混排，类型徽章区分两类', async () => {
    const wrapper = mount(CustomerOrderView, { global: { stubs } })
    await flushPromises()
    await switchToRecordsTab(wrapper)

    const badges = wrapper.findAll('.co-type-badge')
    expect(badges.length).toBe(2)
    expect(badges[0]!.classes()).toContain('order')
    expect(badges[0]!.text()).toBe('订单')
    expect(badges[1]!.classes()).toContain('stockin')
    expect(badges[1]!.text()).toBe('备货')
  })

  it('记录查询页签：一个搜索框 + 查询按钮，不再有筛选面板与类型切换', async () => {
    const wrapper = mount(CustomerOrderView, { global: { stubs } })
    await flushPromises()
    await switchToRecordsTab(wrapper)

    // 搜索框存在且带 placeholder
    const input = wrapper.find('input.co-record-search')
    expect(input.exists()).toBe(true)
    expect(input.attributes('placeholder')).toContain('单号')
    expect(input.attributes('placeholder')).toContain('客户')

    // 查询按钮存在
    const searchBtn = wrapper.find('.co-search-tool').findAll('button').filter((b) => b.text().includes('查询'))
    expect(searchBtn.length).toBe(1)

    // 筛选面板与类型切换已删除
    expect(wrapper.find('.co-filter-panel').exists()).toBe(false)
    expect(wrapper.find('.co-record-type-switch').exists()).toBe(false)
    // 旧的六个筛选控件全部消失
    expect(wrapper.find('#co-filter-customer').exists()).toBe(false)
    expect(wrapper.find('#co-filter-status').exists()).toBe(false)
    expect(wrapper.find('#co-filter-factory').exists()).toBe(false)
    expect(wrapper.find('#co-filter-start').exists()).toBe(false)
    expect(wrapper.find('#co-filter-end').exists()).toBe(false)
  })

  it('搜索框输入关键字点「查询」：请求带 keyword 参数并回到第 1 页', async () => {
    const wrapper = mount(CustomerOrderView, { global: { stubs } })
    await flushPromises()
    await switchToRecordsTab(wrapper)
    expect(mocks.recordsMock).toHaveBeenCalledTimes(1)
    expect(mocks.recordsMock.mock.calls[0]![0]).not.toHaveProperty('keyword')

    const input = wrapper.find('input.co-record-search')
    await input.setValue('宏远')
    // 设值后「清空 ✕」按钮才渲染且排在查询按钮之前，须按文案锁定查询按钮
    const searchBtn = wrapper.find('.co-search-tool').findAll('button').filter((b) => b.text().includes('查询'))
    expect(searchBtn.length).toBe(1)
    await searchBtn[0]!.trigger('click')
    await flushPromises()

    expect(mocks.recordsMock).toHaveBeenCalledTimes(2)
    const lastCall = mocks.recordsMock.mock.calls[1]![0]
    expect(lastCall.keyword).toBe('宏远')
    expect(lastCall.page).toBe(1)
  })

  it('搜索框 ✕ 一键清空并重新查询（keyword 不再下发）', async () => {
    const wrapper = mount(CustomerOrderView, { global: { stubs } })
    await flushPromises()
    await switchToRecordsTab(wrapper)

    const input = wrapper.find('input.co-record-search')
    await input.setValue('宏远')
    const searchBtn = wrapper.find('.co-search-tool').findAll('button').filter((b) => b.text().includes('查询'))
    await searchBtn[0]!.trigger('click')
    await flushPromises()

    const clearBtn = wrapper.find('.co-search-clear')
    expect(clearBtn.exists()).toBe(true)
    await clearBtn.trigger('click')
    await flushPromises()

    const lastCall = mocks.recordsMock.mock.calls.at(-1)![0]
    expect(lastCall.keyword).toBeUndefined()
    expect((input.element as HTMLInputElement).value).toBe('')
  })

  it('备货行无任何操作按钮；订单的每个 SKU 行都有查看与删除，合计行没有', async () => {
    const wrapper = mount(CustomerOrderView, { global: { stubs } })
    await flushPromises()
    await switchToRecordsTab(wrapper)

    // 每个 SKU 各占一行：订单 2 个 SKU → 2 行；备货 1 行
    const rows = wrapper.findAll('tbody tr')
    expect(rows.length).toBe(3)

    // 备货行无详情入口：后端不存在备货详情端点，openDetail 只按订单 id 查（必然 404）
    expect(rows.map((tr) => ({
      view: tr.findAll('.co-btn-info').length,
      del: tr.findAll('.co-btn-danger').length,
    }))).toEqual([
      { view: 1, del: 1 }, // 订单的 SKU 1
      { view: 1, del: 1 }, // 订单的 SKU 2
      { view: 0, del: 0 }, // 备货行
    ])
  })

  it('「抵扣」列已删除：表头不含抵扣，订单行不渲染抵扣徽章', async () => {
    const wrapper = mount(CustomerOrderView, { global: { stubs } })
    await flushPromises()
    await switchToRecordsTab(wrapper)

    const headers = wrapper.findAll('th').map((h) => h.text())
    expect(headers.some((h) => h.includes('抵扣'))).toBe(false)
    // deduct_quantity=40 的订单行不再渲染抵扣徽章
    expect(wrapper.text()).not.toContain('抵扣: 40')
  })

  it('空态文案不再按 recordType 二态切换，统一为「暂无记录」', async () => {
    mocks.recordsMock.mockResolvedValue({ success: true, data: [], total: 0, page: 1, per_page: 20 })
    const wrapper = mount(CustomerOrderView, { global: { stubs } })
    await flushPromises()
    await switchToRecordsTab(wrapper)
    await flushPromises()

    expect(wrapper.text()).toContain('暂无记录')
    expect(wrapper.text()).not.toContain('暂无订单记录')
    expect(wrapper.text()).not.toContain('暂无备货记录')
  })
})
