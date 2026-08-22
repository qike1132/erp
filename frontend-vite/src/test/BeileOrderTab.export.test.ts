import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref, nextTick, defineComponent, h } from 'vue'

const mocks = vi.hoisted(() => ({
  beileListMock: vi.fn(),
  confirmBeileOrderMock: vi.fn(),
  confirmBeileStockinMock: vi.fn(),
  refetchMock: vi.fn(),
  setQueryDataMock: vi.fn(),
  queryData: null as unknown as ReturnType<typeof ref<unknown>>,
  downloadCsvMock: vi.fn(),
  printHtmlMock: vi.fn(),
  downloadXlsMock: vi.fn(),
  hasPermissionMock: vi.fn((_code: string) => true),
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
    hasPermission: mocks.hasPermissionMock,
  }),
}))

vi.mock('@/utils/xls', () => ({
  downloadXls: mocks.downloadXlsMock,
}))

vi.mock('@/utils/print', () => ({
  printHtml: mocks.printHtmlMock,
}))

import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'
import HubeiView from '@/views/hubei/HubeiView.vue'
import type { OrderListApiResponse } from '@/api/order'

Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
  configurable: true,
  get() {
    return 600
  },
})

const stubs = {
  UiSpinner: { template: '<span class="ui-spinner-stub" />' },
  UiPagination: { template: '<div class="ui-pagination-stub" />' },
  UiButton: { template: '<button type="button"><slot /></button>' },
  UiCheckbox: {
    props: ['checked'],
    emits: ['update:checked'],
    template: '<input type="checkbox" :checked="checked" @change="$emit(\'update:checked\', $event.target.checked)" />',
  },
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
  FontAwesomeIcon: { template: '<span class="fa-stub" />' },
  // HubeiSearchBar 内部含 PrimeVue AutoComplete，jsdom 渲染失败，整体 stub 掉
  HubeiSearchBar: { template: '<div class="hubei-searchbar-stub" />' },
  UiAutocomplete: { template: '<input class="ui-autocomplete-stub" />' },
}

function makeListResponse(overrides: Partial<OrderListApiResponse> = {}): OrderListApiResponse {
  return {
    success: true,
    total: 2,
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
        customer: '客户A',
        order_date: '2026-08-12',
        product_name: '产品A',
        product_id: 1,
        quantity: 10,
        deduct_quantity: 0,
        deduct_stock: false,
        note: '加急',
        status: '待备货',
        factories: ['湖北'],
        items: [{ id: 1, product_name: '产品A', product_barcode: '690001', quantity: 10, note: '' }],
      },
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
    ],
    ...overrides,
  } as OrderListApiResponse
}

async function mountView() {
  const wrapper = mount(HubeiView, { global: { plugins: [createPinia()], stubs } })
  await flushPromises()
  await nextTick()
  return wrapper
}

describe('BeileOrderTab 导出与打印功能（HubeiView 头部按钮）', () => {
  beforeEach(() => {
    mocks.beileListMock.mockReset()
    mocks.confirmBeileOrderMock.mockReset()
    mocks.confirmBeileStockinMock.mockReset()
    mocks.refetchMock.mockReset()
    mocks.setQueryDataMock.mockReset()
    mocks.downloadCsvMock.mockReset()
    mocks.downloadXlsMock.mockReset()
    mocks.printHtmlMock.mockReset()

    mocks.hasPermissionMock.mockReset()
    mocks.hasPermissionMock.mockReturnValue(true)
    mocks.setQueryDataMock.mockImplementation((_key: unknown, updater: unknown) => {
      if (typeof updater === 'function' && mocks.queryData) {
        mocks.queryData.value = updater(mocks.queryData.value)
      }
    })
    mocks.queryData.value = makeListResponse()
  })

  it('有权限时显示导出和打印按钮', async () => {
    const wrapper = await mountView()
    const exportBtn = wrapper.find('.bo-header-btn--export')
    const printBtn = wrapper.find('.bo-header-btn--print')
    expect(exportBtn.exists()).toBe(true)
    expect(printBtn.exists()).toBe(true)
  })

  it('无导出权限时隐藏导出按钮', async () => {
    mocks.hasPermissionMock.mockImplementation((code: string) => code !== 'beile_order_export')
    const wrapper = await mountView()
    expect(wrapper.find('.bo-header-btn--export').exists()).toBe(false)
    expect(wrapper.find('.bo-header-btn--print').exists()).toBe(true)
  })

  it('无打印权限时隐藏打印按钮和复选框列', async () => {
    mocks.hasPermissionMock.mockImplementation((code: string) => code !== 'beile_order_print')
    const wrapper = await mountView()
    expect(wrapper.find('.bo-header-btn--print').exists()).toBe(false)
    expect(wrapper.find('.bo-th-select').exists()).toBe(false)
    expect(wrapper.findAll('.bo-td-select').length).toBe(0)
  })

  it('点击导出按钮调用 downloadXls，文件名含状态与日期，HTML 含居中标题', async () => {
    const wrapper = await mountView()
    await wrapper.find('.bo-header-btn--export').trigger('click')
    await flushPromises()
    await flushPromises()
    expect(mocks.downloadXlsMock).toHaveBeenCalledTimes(1)
    const [html, filename] = mocks.downloadXlsMock.mock.calls[0]!
    expect(filename).toMatch(/^湖北订单_未确认_\d{4}-\d{2}-\d{2}\.xls$/)
    expect(html).toContain('湖北订单汇总')
    expect(html).toContain('text-align:center')
    expect(html).toContain('<table>')
    expect(html).toContain('订单类型')
    expect(html).toContain('产品名称')
    expect(html).toContain('数量')
    expect(html).not.toContain('条码')
    expect(html).not.toContain('确认状态')
    expect(html).toContain('<tbody>')
  })

  it('打印按钮在未选中时禁用', async () => {
    const wrapper = await mountView()
    const printBtn = wrapper.find('.bo-header-btn--print')
    expect(printBtn.attributes('disabled')).toBeDefined()
  })

  it('勾选订单后打印按钮启用，点击调用 printTable 汇总表', async () => {
    const wrapper = await mountView()
    const checkboxes = wrapper.findAll('.bo-td-select input, .bo-td-select [role="checkbox"]')
    expect(checkboxes.length).toBeGreaterThan(0)
    await checkboxes[0]!.setValue(true)
    await nextTick()
    const printBtn = wrapper.find('.bo-header-btn--print')
    expect(printBtn.attributes('disabled')).toBeUndefined()
    await printBtn.trigger('click')
    await flushPromises()
    expect(mocks.printHtmlMock).toHaveBeenCalledTimes(1)
    const [title, bodyHtml] = mocks.printHtmlMock.mock.calls[0]!
    expect(title).toContain('1')
    expect(bodyHtml).toContain('订单类型')
    expect(bodyHtml).toContain('客户名称')
    expect(bodyHtml).toContain('产品名称')
    expect(bodyHtml).not.toContain('条码')
    expect(bodyHtml).not.toContain('确认状态')
  })

  it('表头全选复选框勾选后选中所有当前页订单', async () => {
    const wrapper = await mountView()
    const headerCheckbox = wrapper.find('.bo-th-select input')
    expect(headerCheckbox.exists()).toBe(true)
    await headerCheckbox.setValue(true)
    await nextTick()
    expect(wrapper.find('.bo-selected-count').text()).toContain('2')
    await wrapper.find('.bo-header-btn--print').trigger('click')
    await flushPromises()
    expect(mocks.printHtmlMock).toHaveBeenCalledTimes(1)
    const [title, bodyHtml] = mocks.printHtmlMock.mock.calls[0]!
    expect(title).toContain('2')
    // 2 个订单各 1 个 SKU = 2 行
    expect((bodyHtml.match(/<tr>/g) || []).length).toBe(2 + 1) // +1 thead
  })

  it('多 SKU 订单展开为多行：首行填订单级信息，后续行仅填产品明细', async () => {
    mocks.queryData.value = makeListResponse({
      total: 1,
      data: [
        {
          id: 301,
          record_type: 'order',
          confirmed: false,
          confirmed_at: null,
          confirmed_by: null,
          order_no: 'PO-301',
          customer: '多SKU客户',
          order_date: '2026-08-19',
          product_name: '产品X',
          product_id: 1,
          quantity: 30,
          deduct_quantity: 0,
          deduct_stock: false,
          note: '备注A',
          status: '待备货',
          factories: ['湖北'],
          items: [
            { id: 1, product_name: '产品X', product_barcode: '690001', quantity: 10, note: '' },
            { id: 2, product_name: '产品Y', product_barcode: '690002', quantity: 20, note: '' },
          ],
        },
      ] as unknown as OrderListApiResponse['data'],
    })
    const wrapper = await mountView()

    // 导出：HTML tbody 应含 2 行（2 个 SKU）
    await wrapper.find('.bo-header-btn--export').trigger('click')
    await flushPromises()
    await flushPromises()
    const [exportHtml, exportFilename] = mocks.downloadXlsMock.mock.calls[0]!
    expect(exportFilename).toMatch(/\.xls$/)
    const exportTrCount = (exportHtml.match(/<tr>/g) || []).length
    // 1 thead + 2 tbody = 3 <tr>
    expect(exportTrCount).toBe(3)

    // 打印：勾选后 printHtml bodyHtml 应含 rowspan 合并
    const checkbox = wrapper.find('.bo-td-select input')
    await checkbox.setValue(true)
    await nextTick()
    await wrapper.find('.bo-header-btn--print').trigger('click')
    await flushPromises()
    const [, printBody] = mocks.printHtmlMock.mock.calls[0]!
    // 2 个 SKU → tbody 2 行 + thead 1 行 = 3 <tr>
    expect((printBody.match(/<tr>/g) || []).length).toBe(3)
    // 订单级列应使用 rowspan="2" 合并
    expect(printBody).toContain('rowspan="2"')
    // 首行含产品 X，次行含产品 Y
    expect(printBody).toContain('产品X')
    expect(printBody).toContain('产品Y')
  })
})
