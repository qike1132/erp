import { describe, it, expect, vi, beforeEach } from 'vitest'

// Hoisted mock state — vi.mock factories are hoisted to the top of the file,
// so we keep mutable mocks inside vi.hoisted() and reference them by name.
const mocks = vi.hoisted(() => ({
  recordsMock: vi.fn(),
  orderDetailMock: vi.fn(),
  customerActiveNamesMock: vi.fn(),
  editStockinMock: vi.fn(),
  deleteStockinMock: vi.fn(),
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
  stockApi: {
    // 备货行的编辑/删除（记录查询页新增入口）：后端 PUT /stock/in/edit/{id}、DELETE /stock/in/delete/{id}
    editStockin: mocks.editStockinMock,
    deleteStockin: mocks.deleteStockinMock,
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
    mocks.editStockinMock.mockReset()
    mocks.deleteStockinMock.mockReset()
    mocks.editStockinMock.mockResolvedValue({ success: true, message: '入库编辑成功！' })
    mocks.deleteStockinMock.mockResolvedValue({ success: true, message: '入库删除成功！' })
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

    // 2026-10-01：搜索工具条在卡片页头里，与「录入 / 记录查询」TAB 同排；「记录列表」标题与图标已删除
    expect(wrapper.find('.page-card-header .co-search-tool').exists()).toBe(true)
    expect(wrapper.find('.co-records-title').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('记录列表')

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

  it('搜索工具条只属于「记录查询」页签，录入页签下不渲染', async () => {
    const wrapper = mount(CustomerOrderView, { global: { stubs } })
    await flushPromises()

    // 初始在「录入」页签
    expect(wrapper.find('input.co-record-search').exists()).toBe(false)

    await switchToRecordsTab(wrapper)
    expect(wrapper.find('input.co-record-search').exists()).toBe(true)
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

  it('备货行给编辑与删除（不给查看）；订单的每个 SKU 行都有查看与删除', async () => {
    const wrapper = mount(CustomerOrderView, { global: { stubs } })
    await flushPromises()
    await switchToRecordsTab(wrapper)

    // 每个 SKU 各占一行：订单 2 个 SKU → 2 行；备货 1 行
    const rows = wrapper.findAll('tbody tr')
    expect(rows.length).toBe(3)

    // 备货无详情端点（openDetail 只按订单 id 查，必然 404），故没有查看入口；
    // 编辑/删除走 /stock/in/edit、/stock/in/delete（2026-10-01 用户要求补上）。
    expect(rows.map((tr) => ({
      view: tr.findAll('.co-btn-info').length,
      edit: tr.findAll('.co-btn-edit').length,
      del: tr.findAll('.co-btn-danger').length,
    }))).toEqual([
      { view: 1, edit: 0, del: 1 }, // 订单的 SKU 1
      { view: 1, edit: 0, del: 1 }, // 订单的 SKU 2
      { view: 0, edit: 1, del: 1 }, // 备货行
    ])
  })

  it('备货行点「编辑」打开弹窗，保存走 PUT /stock/in/edit/{id} 且带列表行上的原值', async () => {
    const wrapper = mount(CustomerOrderView, { global: { stubs } })
    await flushPromises()
    await switchToRecordsTab(wrapper)

    await wrapper.findAll('.co-btn-edit')[0]!.trigger('click')
    await nextTick()

    // 弹窗字段：产品只读、数量/客户/日期/备注可改（后端 StockInUpdate 就这四个）。
    // 标题与产品名走 UiDialog/UiInput 的 stub，不渲染文本，故用字段 id 定位。
    const dialog = wrapper.find('.ui-dialog-stub')
    expect(dialog.exists(), '编辑弹窗应打开').toBe(true)
    const qtyInput = dialog.find('#es-stockin-quantity')
    expect(qtyInput.exists(), '备货数量字段应存在').toBe(true)
    expect((qtyInput.element as HTMLInputElement).value).toBe('500')

    const saveBtn = dialog.findAll('button').find((b) => b.text().includes('保存'))!
    await saveBtn.trigger('click')
    await flushPromises()

    expect(mocks.editStockinMock).toHaveBeenCalledTimes(1)
    const [id, payload] = mocks.editStockinMock.mock.calls[0]!
    expect(id).toBe(2) // 备货记录自身的 id
    expect(payload).toEqual({
      quantity: 500,
      customer: '客户B',
      // 列表下发 '2026-09-30 09:05'，接口只收日期（时间部分由后端保留原值）
      stockin_date: '2026-09-30',
      note: '',
    })
    // 写入成功后重新拉列表
    expect(mocks.recordsMock).toHaveBeenCalledTimes(2)
  })

  it('备货行点「删除」：确认后走 DELETE /stock/in/delete/{id} 并刷新列表', async () => {
    const wrapper = mount(CustomerOrderView, { global: { stubs } })
    await flushPromises()
    await switchToRecordsTab(wrapper)

    // 备货行是第 3 行（订单 2 个 SKU 之后）
    const stockinRow = wrapper.findAll('tbody tr')[2]!
    await stockinRow.find('.co-btn-danger').trigger('click')
    await flushPromises()

    expect(mocks.deleteStockinMock).toHaveBeenCalledWith(2)
    expect(mocks.recordsMock).toHaveBeenCalledTimes(2)
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
