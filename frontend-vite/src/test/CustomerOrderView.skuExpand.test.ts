import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// Hoisted mock state — vi.mock factories are hoisted to the top of the file,
// so we keep mutable mocks inside vi.hoisted() and reference them by name.
const mocks = vi.hoisted(() => ({
  orderListMock: vi.fn(),
  recordsMock: vi.fn(),
  orderDetailMock: vi.fn(),
  customerActiveNamesMock: vi.fn(),
  getRequestMock: vi.fn(),
  postRequestMock: vi.fn(),
}))

vi.mock('@/api', () => ({
  orderApi: {
    list: mocks.orderListMock,
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
    stockins: vi.fn().mockResolvedValue({ data: [], total: 0 }),
  },
  customerApi: {
    activeNames: mocks.customerActiveNamesMock,
  },
}))

vi.mock('@/api/request', () => ({
  get: mocks.getRequestMock,
  post: mocks.postRequestMock,
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

// Stub child components that aren't relevant to SKU expand behavior.
// UiDialog must render its slot when `open` is true so we can inspect the
// SKU details table that CustomerOrderView projects into it.
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

// Helper: switch the mounted view to the "记录查询" tab so that
// fetchOrders() is triggered (the watch on activeTab calls it).
async function switchToRecordsTab(wrapper: ReturnType<typeof mount>) {
  const recordsTab = wrapper.findAll('button.co-tab-btn').find((b) => b.text().includes('记录查询'))
  expect(recordsTab, '记录查询 tab button should exist').toBeTruthy()
  await recordsTab!.trigger('click')
  await flushPromises()
  await nextTick()
}

describe('CustomerOrderView SKU expand behavior (SubTask 7.4)', () => {
  beforeEach(() => {
    // useOrderForm 内使用 useCatalogStore()，需提供活跃 Pinia 实例
    setActivePinia(createPinia())
    mocks.orderListMock.mockReset()
    mocks.recordsMock.mockReset()
    mocks.orderDetailMock.mockReset()
    mocks.customerActiveNamesMock.mockReset()
    mocks.getRequestMock.mockReset()
    mocks.postRequestMock.mockReset()
    mocks.customerActiveNamesMock.mockResolvedValue({ names: [] })
    mocks.getRequestMock.mockResolvedValue({})
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('order list row shows multi-SKU count badge when items.length === 3', async () => {
    mocks.recordsMock.mockResolvedValue({
      data: [
        {
          id: 1,
          // 记录列表行必带 record_type（后端 /orders/records 统一契约）；操作列按它决定是否有详情入口
          record_type: 'order',
          order_no: 'ORD-001',
          customer: '客户A',
          order_date: '2024-01-01',
          product: { name: '产品A', barcode: '69001' },
          quantity: 10,
          deduct_quantity: 0,
          items: [
            { id: 1, product_name: 'SKU1', quantity: 4 },
            { id: 2, product_name: 'SKU2', quantity: 3 },
            { id: 3, product_name: 'SKU3', quantity: 3 },
          ],
        },
      ],
      total: 1,
    })

    const wrapper = mount(CustomerOrderView, { global: { stubs } })
    await flushPromises()
    await switchToRecordsTab(wrapper)

    // SKU 数量 column renders a success badge (count > 1) — see CustomerOrderView.vue:354-358
    const successBadge = wrapper.find('.co-badge-tag.co-badge-success')
    expect(successBadge.exists(), 'multi-SKU success badge should be rendered').toBe(true)
    expect(successBadge.text()).toBe('3')
  })

  it('order list row shows muted badge "1" for single-SKU order', async () => {
    mocks.recordsMock.mockResolvedValue({
      data: [
        {
          id: 1,
          // 记录列表行必带 record_type（后端 /orders/records 统一契约）；操作列按它决定是否有详情入口
          record_type: 'order',
          order_no: 'ORD-001',
          customer: '客户A',
          order_date: '2024-01-01',
          product: { name: '产品A', barcode: '69001' },
          quantity: 10,
          deduct_quantity: 0,
          items: [{ id: 1, product_name: 'SKU1', quantity: 10 }],
        },
      ],
      total: 1,
    })

    const wrapper = mount(CustomerOrderView, { global: { stubs } })
    await flushPromises()
    await switchToRecordsTab(wrapper)

    // Single SKU → muted badge with text "1" (NOT multi-SKU success badge)
    const mutedBadge = wrapper.find('.co-badge-tag.co-badge-muted')
    expect(mutedBadge.exists(), 'single-SKU muted badge should be rendered').toBe(true)
    expect(mutedBadge.text()).toBe('1')

    // No multi-SKU success badge should be present (deduct_quantity is 0)
    expect(wrapper.find('.co-badge-tag.co-badge-success').exists()).toBe(false)
  })

  it('detail dialog shows SKU details table when detailData.items.length > 1', async () => {
    mocks.recordsMock.mockResolvedValue({
      data: [
        {
          id: 1,
          // 记录列表行必带 record_type（后端 /orders/records 统一契约）；操作列按它决定是否有详情入口
          record_type: 'order',
          order_no: 'ORD-001',
          customer: '客户A',
          order_date: '2024-01-01',
          product: { name: '产品A', barcode: '69001', id: 1 },
          quantity: 10,
          deduct_quantity: 0,
          items: [
            { id: 1, product_name: 'SKU1', quantity: 5 },
            { id: 2, product_name: 'SKU2', quantity: 5 },
          ],
        },
      ],
      total: 1,
    })

    mocks.orderDetailMock.mockResolvedValue({
      id: 1,
      order_no: 'ORD-001',
      customer: '客户A',
      order_date: '2024-01-01',
      product: { name: '产品A', barcode: '69001', id: 1 },
      quantity: 10,
      deduct_quantity: 0,
      status: '待备货',
      items: [
        {
          id: 1,
          product_name: 'SKU1',
          product_barcode: 'B001',
          quantity: 5,
          deduct_quantity: 0,
          note: '',
        },
        {
          id: 2,
          product_name: 'SKU2',
          product_barcode: 'B002',
          quantity: 5,
          deduct_quantity: 0,
          note: '',
        },
      ],
    })

    const wrapper = mount(CustomerOrderView, { global: { stubs } })
    await flushPromises()
    await switchToRecordsTab(wrapper)

    // Click the row's detail button → openDetail(item) → orderApi.detail(id)
    // 详情按钮的可访问名按行带上订单号（便于读屏器区分），故用前缀匹配而非全等
    const detailBtn = wrapper.find('button[aria-label^="查看"]')
    expect(detailBtn.exists(), 'detail button should exist').toBe(true)
    await detailBtn.trigger('click')
    await flushPromises()
    await nextTick()

    // Detail dialog should be open and show SKU details section
    expect(mocks.orderDetailMock).toHaveBeenCalledWith(1)

    const dialogText = wrapper.text()
    expect(dialogText).toContain('订单明细')
    expect(dialogText).toContain('2 个 SKU')

    // SKU details table should render 2 rows (one per SKU)
    const skuRows = wrapper.findAll('.oe-sku-table tbody tr')
    expect(skuRows.length).toBe(2)

    // Both SKU names should appear in the rendered dialog
    expect(dialogText).toContain('SKU1')
    expect(dialogText).toContain('SKU2')
  })

  it('detail dialog hides SKU details table when detailData.items.length === 1', async () => {
    mocks.recordsMock.mockResolvedValue({
      data: [
        {
          id: 1,
          // 记录列表行必带 record_type（后端 /orders/records 统一契约）；操作列按它决定是否有详情入口
          record_type: 'order',
          order_no: 'ORD-001',
          customer: '客户A',
          order_date: '2024-01-01',
          product: { name: '产品A', barcode: '69001', id: 1 },
          quantity: 10,
          deduct_quantity: 0,
          items: [{ id: 1, product_name: 'SKU1', quantity: 10 }],
        },
      ],
      total: 1,
    })

    mocks.orderDetailMock.mockResolvedValue({
      id: 1,
      order_no: 'ORD-001',
      customer: '客户A',
      order_date: '2024-01-01',
      product: { name: '产品A', barcode: '69001', id: 1 },
      quantity: 10,
      deduct_quantity: 0,
      status: '待备货',
      items: [{ id: 1, product_name: 'SKU1', quantity: 10 }],
    })

    const wrapper = mount(CustomerOrderView, { global: { stubs } })
    await flushPromises()
    await switchToRecordsTab(wrapper)

    // 详情按钮的可访问名按行带上订单号（便于读屏器区分），故用前缀匹配而非全等
    const detailBtn = wrapper.find('button[aria-label^="查看"]')
    expect(detailBtn.exists()).toBe(true)
    await detailBtn.trigger('click')
    await flushPromises()
    await nextTick()

    expect(mocks.orderDetailMock).toHaveBeenCalledWith(1)

    // SKU details table should NOT be rendered (items.length <= 1)
    expect(wrapper.find('.oe-sku-table').exists(), 'SKU table should be hidden for single-SKU detail').toBe(false)

    const dialogText = wrapper.text()
    expect(dialogText).not.toContain('订单明细')
    expect(dialogText).not.toContain('个 SKU')
  })

  it('detail dialog hides SKU details table when detailData.items is empty', async () => {
    mocks.recordsMock.mockResolvedValue({
      data: [
        {
          id: 2,
          record_type: 'order',
          order_no: 'ORD-002',
          customer: '客户B',
          order_date: '2024-02-02',
          product: { name: '产品B', barcode: '69002', id: 2 },
          quantity: 7,
          deduct_quantity: 0,
          items: [],
        },
      ],
      total: 1,
    })

    mocks.orderDetailMock.mockResolvedValue({
      id: 2,
      order_no: 'ORD-002',
      customer: '客户B',
      order_date: '2024-02-02',
      product: { name: '产品B', barcode: '69002', id: 2 },
      quantity: 7,
      deduct_quantity: 0,
      status: '待备货',
      items: [],
    })

    const wrapper = mount(CustomerOrderView, { global: { stubs } })
    await flushPromises()
    await switchToRecordsTab(wrapper)

    // 详情按钮的可访问名按行带上订单号（便于读屏器区分），故用前缀匹配而非全等
    const detailBtn = wrapper.find('button[aria-label^="查看"]')
    expect(detailBtn.exists()).toBe(true)
    await detailBtn.trigger('click')
    await flushPromises()
    await nextTick()

    expect(mocks.orderDetailMock).toHaveBeenCalledWith(2)

    // Empty items array → v-if "detailData.items?.length > 1" is false → table hidden
    expect(wrapper.find('.oe-sku-table').exists(), 'SKU table should be hidden when items is empty').toBe(false)

    const dialogText = wrapper.text()
    expect(dialogText).not.toContain('订单明细')
  })
})
