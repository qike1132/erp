import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
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

import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils'
import HubeiView from '@/views/hubei/HubeiView.vue'
import { buildSummaryTbody } from '@/views/beile-order/composables/useBeileOrders'
import type { BeileOrderRow } from '@/views/beile-order/composables/useBeileOrders'
import type { OrderListApiResponse } from '@/api/order'

/** 测试卫生：HubeiView 页头含 v-if 动态节点，未卸载的组件树会在后续测试期间
 *  触发子组件重新 mount（VTU stub 拦截已失效）→ 实例化真实 HubeiSearchBar 并抛错。
 *  统一在 afterEach 卸载。 */
enableAutoUnmount(afterEach)

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
  UiDialog: {
    props: ['open', 'title', 'maxWidthClass'],
    template: '<div v-if="open" class="ui-dialog-stub"><slot /><slot name="footer" /></div>',
  },
  HubeiSearchBar: { template: '<div class="hu-search-stub" />' },
  VirtualList: {
    props: ['items'],
    methods: {
      scrollToTop() {},
    },
    template: '<div class="vl-stub"><div v-for="item in items" :key="item.id" class="vl-row"><slot :item="item" /></div></div>',
  },
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

/**
 * 测试包装组件：HubeiView 自身在 setup 中调用 provideBeileOrders 创建唯一状态实例。
 * 导出/打印按钮已由表格上方工具栏上移至页头右上角（.hu-order-actions），
 * 故直接挂载 HubeiView 而非 BeileOrderTab。
 */
const TestHost = defineComponent({
  setup() {
    return () => h(HubeiView)
  },
})

async function mountTab() {
  const wrapper = mount(TestHost, { global: { stubs } })
  await flushPromises()
  await nextTick()
  return wrapper
}

describe('BeileOrderTab 导出与打印功能', () => {
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
    const wrapper = await mountTab()
    const exportBtn = wrapper.find('.bo-toolbar-btn--export')
    const printBtn = wrapper.find('.bo-toolbar-btn--print')
    expect(exportBtn.exists()).toBe(true)
    expect(printBtn.exists()).toBe(true)
  })

  it('无导出权限时隐藏导出按钮', async () => {
    mocks.hasPermissionMock.mockImplementation((code: string) => code !== 'beile_order_export')
    const wrapper = await mountTab()
    expect(wrapper.find('.bo-toolbar-btn--export').exists()).toBe(false)
    expect(wrapper.find('.bo-toolbar-btn--print').exists()).toBe(true)
  })

  it('无打印权限时隐藏打印按钮和复选框列', async () => {
    mocks.hasPermissionMock.mockImplementation((code: string) => code !== 'beile_order_print')
    const wrapper = await mountTab()
    expect(wrapper.find('.bo-toolbar-btn--print').exists()).toBe(false)
    expect(wrapper.find('.bo-th-select').exists()).toBe(false)
    expect(wrapper.findAll('.bo-td-select').length).toBe(0)
  })

  it('点击导出按钮调用 downloadXls，文件名含状态与日期，HTML 含居中标题', async () => {
    const wrapper = await mountTab()
    await wrapper.find('.bo-toolbar-btn--export').trigger('click')
    await flushPromises()
    expect(mocks.downloadXlsMock).toHaveBeenCalledTimes(1)
    const [html, filename] = mocks.downloadXlsMock.mock.calls[0]!
    expect(filename).toMatch(/^湖北订单_未确认_\d{4}-\d{2}-\d{2}\.xls$/)
    expect(html).toContain('湖北订单汇总')
    expect(html).toContain('text-align:center')
    expect(html).toContain('<table>')
    expect(html).toContain('订单类型')
    expect(html).toContain('订单号')
    expect(html).toContain('产品名称')
    expect(html).toContain('数量')
    expect(html).toContain('订单数量')
    expect(html).toContain('生产数量')
    expect(html).not.toContain('备品数量')
    expect(html).not.toContain('条码')
    expect(html).not.toContain('确认状态')
    expect(html).toContain('<tbody>')
  })

  it('打印按钮在未选中时禁用', async () => {
    const wrapper = await mountTab()
    const printBtn = wrapper.find('.bo-toolbar-btn--print')
    expect(printBtn.attributes('disabled')).toBeDefined()
  })

  it('仅导出勾选的订单：勾选 1 条后导出文件不含未勾选行，标题附已选条数（BUG：导出与勾选不一致）', async () => {
    const wrapper = await mountTab()
    const checkboxes = wrapper.findAll('.bo-td-select input, .bo-td-select [role="checkbox"]')
    expect(checkboxes.length).toBe(2)
    await checkboxes[0]!.trigger('click')
    await nextTick()
    expect(wrapper.find('.bo-selected-count').text()).toContain('1')
    await wrapper.find('.bo-toolbar-btn--export').trigger('click')
    await flushPromises()
    expect(mocks.downloadXlsMock).toHaveBeenCalledTimes(1)
    const [html] = mocks.downloadXlsMock.mock.calls[0]!
    // 勾选行（订单 101：客户A/产品A）出现
    expect(html).toContain('客户A')
    expect(html).toContain('产品A')
    // 未勾选行（备货 201：备货客户/产品C）不出现
    expect(html).not.toContain('备货客户')
    expect(html).not.toContain('产品C')
    // 标题附条数，便于核对导出范围 == 勾选集合
    expect(html).toContain('已选 1 条')
  })

  it('订单与备货 id 撞号时勾选其一仅导出其一（选中键 = record_type:id 复合）', async () => {
    // 订单 id=201 与备货 id=201 同页（不同表 id 可能撞号，后端同源提示）
    mocks.queryData.value = makeListResponse({
      total: 2,
      data: [
        {
          id: 201,
          record_type: 'order',
          confirmed: false,
          confirmed_at: null,
          confirmed_by: null,
          order_no: 'PO-201',
          customer: '订单客户',
          order_date: '2026-08-12',
          product_name: '订单品',
          product_id: 1,
          quantity: 10,
          deduct_quantity: 0,
          deduct_stock: false,
          note: '',
          status: '待备货',
          factories: ['湖北'],
          items: [{ id: 1, product_name: '订单品', product_barcode: '690001', quantity: 10, note: '' }],
        },
        {
          id: 201,
          record_type: 'stockin',
          confirmed: false,
          confirmed_at: null,
          confirmed_by: null,
          customer: '备货客户',
          order_date: '2026-08-10',
          product_name: '备货品',
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
    const checkboxes = wrapper.findAll('.bo-td-select input, .bo-td-select [role="checkbox"]')
    await checkboxes[0]!.trigger('click') // 仅勾选订单行（id 与备货行相同）
    await nextTick()
    expect(wrapper.find('.bo-selected-count').text()).toContain('1')
    await wrapper.find('.bo-toolbar-btn--export').trigger('click')
    await flushPromises()
    const [html] = mocks.downloadXlsMock.mock.calls[0]!
    expect(html).toContain('订单客户')
    expect(html).not.toContain('备货客户')
  })

  it('勾选订单后打印按钮启用，点击调用 printTable 汇总表', async () => {
    const wrapper = await mountTab()
    const checkboxes = wrapper.findAll('.bo-td-select input, .bo-td-select [role="checkbox"]')
    expect(checkboxes.length).toBeGreaterThan(0)
    await checkboxes[0]!.trigger('click')
    await nextTick()
    const printBtn = wrapper.find('.bo-toolbar-btn--print')
    expect(printBtn.attributes('disabled')).toBeUndefined()
    await printBtn.trigger('click')
    await flushPromises()
    expect(mocks.printHtmlMock).toHaveBeenCalledTimes(1)
    const [title, bodyHtml] = mocks.printHtmlMock.mock.calls[0]!
    expect(title).toContain('1')
    expect(bodyHtml).toContain('订单类型')
    expect(bodyHtml).toContain('客户名称')
    expect(bodyHtml).toContain('产品名称')
    expect(bodyHtml).toContain('订单数量')
    expect(bodyHtml).toContain('生产数量')
    expect(bodyHtml).not.toContain('备品数量')
    expect(bodyHtml).not.toContain('条码')
    expect(bodyHtml).not.toContain('确认状态')
  })

  it('表头全选复选框勾选后选中所有当前页订单', async () => {
    const wrapper = await mountTab()
    const headerCheckbox = wrapper.find('.bo-th-select [role="checkbox"]')
    expect(headerCheckbox.exists()).toBe(true)
    await headerCheckbox.trigger('click')
    await nextTick()
    expect(wrapper.find('.bo-selected-count').text()).toContain('2')
    await wrapper.find('.bo-toolbar-btn--print').trigger('click')
    await flushPromises()
    expect(mocks.printHtmlMock).toHaveBeenCalledTimes(1)
    const [title, bodyHtml] = mocks.printHtmlMock.mock.calls[0]!
    expect(title).toContain('2')
    // 2 个订单各 1 个 SKU = 2 行
    expect((bodyHtml.match(/<tr>/g) || []).length).toBe(2 + 1) // +1 thead
  })

  it('多 SKU 订单：逐 SKU 输出订单数量/生产数量 + 追加订单级「合计」行（FIX-3）', async () => {
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
    const wrapper = await mountTab()

    // 导出：2 个 SKU 逐行 + 1 行订单级合计 = 3 tbody 行
    await wrapper.find('.bo-toolbar-btn--export').trigger('click')
    await flushPromises()
    const [exportHtml, exportFilename] = mocks.downloadXlsMock.mock.calls[0]!
    expect(exportFilename).toMatch(/\.xls$/)
    const exportTrCount = (exportHtml.match(/<tr>/g) || []).length
    // 1 thead + 3 tbody = 4 <tr>
    expect(exportTrCount).toBe(4)
    // 逐 SKU 数量出现在导出 HTML（不再整段 rowspan 到订单级）
    expect(exportHtml).toContain('产品X')
    expect(exportHtml).toContain('产品Y')
    expect(exportHtml).toContain('合计')

    // 打印：勾选后 printHtml bodyHtml 亦为 1 thead + 3 tbody = 4 <tr>
    const checkbox = wrapper.find('.bo-td-select [role="checkbox"]')
    await checkbox.trigger('click')
    await nextTick()
    await wrapper.find('.bo-toolbar-btn--print').trigger('click')
    await flushPromises()
    const [, printBody] = mocks.printHtmlMock.mock.calls[0]!
    expect((printBody.match(/<tr>/g) || []).length).toBe(4)
    // 订单级列（订单类型/客户等）用 rowspan="3" 合并跨「2 SKU 行 + 合计行」
    expect(printBody).toContain('rowspan="3"')
    expect(printBody).toContain('产品X')
    expect(printBody).toContain('产品Y')
  })

  it('导出/打印同源（AC-12）：已下单行数量取 purchase_order_qty、生产数量=订单+备品、小义开单「已开单」；未下单行生产数量为「—」、小义开单「未开单」；无备品数量列', async () => {
    mocks.queryData.value = makeListResponse({
      total: 2,
      data: [
        {
          id: 101,
          record_type: 'order',
          confirmed: true,
          confirmed_at: '2026-08-12T10:00:00',
          confirmed_by: 'admin',
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
          items: [{ id: 1, product_name: '产品A', product_barcode: '690001', quantity: 10, note: '' }],
          is_ordered: true,
          purchase_order_qty: 8,
          spare_quantity: 2,
          spare_rate: 5,
        },
        {
          id: 102,
          record_type: 'order',
          confirmed: true,
          confirmed_at: '2026-08-12T10:00:00',
          confirmed_by: 'admin',
          order_no: 'PO-102',
          customer: '未下单客户',
          order_date: '2026-08-11',
          product_name: '产品B',
          product_id: 2,
          quantity: 30,
          deduct_quantity: 0,
          deduct_stock: false,
          note: '',
          status: '待备货',
          factories: ['湖北'],
          items: [
            { id: 2, product_name: '产品B', product_barcode: '690002', quantity: 10, note: '' },
            { id: 3, product_name: '产品B2', product_barcode: '690003', quantity: 20, note: '' },
          ],
          is_ordered: false,
          purchase_order_qty: 0,
          spare_quantity: 0,
        },
      ] as unknown as OrderListApiResponse['data'],
    })
    const wrapper = await mountTab()

    await wrapper.find('.bo-toolbar-btn--export').trigger('click')
    await flushPromises()
    const [html] = mocks.downloadXlsMock.mock.calls[0]!

    const doc = new DOMParser().parseFromString(html, 'text/html')
    const rows = [...doc.querySelectorAll('tbody tr')]
    // 行序：id101(1 SKU=1行) + id102(2 SKU=2行 + 合计1行) = 4 行
    expect(rows.length).toBe(4)

    const cellsOf = (tr: Element) => [...tr.querySelectorAll('td')].map((td) => td.textContent || '')
    // 列序：订单类型(0) | 订单号(1) | 下单时间(2) | 客户(3) | 工厂(4)
    //       | 产品名称(5) | 订单数量(6) | 生产数量(7) | 小义开单(8) | 备注(9)
    // 已下单（单 SKU）行：订单数量=8、生产数量=8+2=10、小义开单=已开单
    const orderedCells = cellsOf(rows[0]!)
    expect(orderedCells[1]).toBe('PO-101')
    expect(orderedCells[5]).toBe('产品A')
    expect(orderedCells[6]).toBe('8')
    expect(orderedCells[7]).toBe('10')
    expect(orderedCells[8]).toBe('已开单')
    // 未下单（多 SKU）订单：逐 SKU 输出订单数量，生产数量=—（不可派生）
    // 行1 = 产品B（订单数量=10，携带订单级 rowspan 单元格）
    const sku1Cells = cellsOf(rows[1]!)
    expect(sku1Cells[1]).toBe('PO-102')
    expect(sku1Cells[5]).toBe('产品B')
    expect(sku1Cells[6]).toBe('10')
    expect(sku1Cells[7]).toBe('—')
    expect(sku1Cells[8]).toBe('未开单')
    // 行2 = 产品B2（订单数量=20；订单级列由 rowspan 覆盖，故仅 4 个 td）
    const sku2Cells = cellsOf(rows[2]!)
    expect(sku2Cells[0]).toBe('产品B2')
    expect(sku2Cells[1]).toBe('20')
    expect(sku2Cells[2]).toBe('—')
    // 行3 = 订单级「合计」（订单数量=各 SKU 之和=30，生产数量=—）
    const totalCells = cellsOf(rows[3]!)
    expect(totalCells[0]).toBe('合计')
    expect(totalCells[1]).toBe('30')
    expect(totalCells[2]).toBe('—')
  })

  it('列表 DOM：表头含「订单数量」「生产数量」「SKU」且无「备品数量」列；已下单行生产数量 = 订单数量 + 备品数量，未下单行为「—」', async () => {
    mocks.queryData.value = makeListResponse({
      total: 2,
      unconfirmed_count: 0,
      data: [
        {
          id: 101,
          record_type: 'order',
          confirmed: true,
          confirmed_at: '2026-08-12T10:00:00',
          confirmed_by: 'admin',
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
          items: [{ id: 1, product_name: '产品A', product_barcode: '690001', quantity: 10, note: '' }],
          is_ordered: true,
          purchase_order_qty: 8,
          spare_quantity: 2,
          spare_rate: 5,
        },
        {
          id: 102,
          record_type: 'order',
          confirmed: true,
          confirmed_at: '2026-08-11T10:00:00',
          confirmed_by: 'admin',
          order_no: 'PO-102',
          customer: '未下单客户',
          order_date: '2026-08-11',
          product_name: '产品B',
          product_id: 2,
          quantity: 30,
          deduct_quantity: 0,
          deduct_stock: false,
          note: '',
          status: '待备货',
          factories: ['湖北'],
          items: [
            { id: 2, product_name: '产品B', product_barcode: '690002', quantity: 10, note: '' },
            { id: 3, product_name: '产品B2', product_barcode: '690003', quantity: 20, note: '' },
          ],
          is_ordered: false,
          purchase_order_qty: 0,
          spare_quantity: 0,
        },
      ] as unknown as OrderListApiResponse['data'],
    })
    const wrapper = await mountTab()

    // 表头：文案 + 列序，备品数量独立列已删除
    const headers = wrapper.findAll('.bo-th').map((h) => h.text())
    expect(headers).toContain('订单数量')
    expect(headers).toContain('生产数量')
    expect(headers).toContain('SKU')
    expect(headers).not.toContain('备品数量')
    expect(headers.indexOf('订单数量')).toBeLessThan(headers.indexOf('生产数量'))
    // 订单号列（2026-09-29 恢复；保留类型列，订单号紧随其后）
    expect(headers).toContain('订单号')
    expect(headers.indexOf('订单号')).toBe(headers.indexOf('订单类型') + 1)

    const rows = wrapper.findAll('.vl-row')
    expect(rows.length).toBe(2)

    // 已下单行（单 SKU）：订单数量 = 8（加粗），生产数量 = 8 + 2 = 10（备品值仅作计算输入，不独立展示）
    const orderedRow = rows[0]!
    expect(orderedRow.find('.bo-qty--ordered').text()).toBe('8')
    expect(orderedRow.find('.bo-prod').text()).toBe('10')

    // 未下单行（多 SKU）：生产数量列显示「—」（不可派生）
    const unorderedRow = rows[1]!
    expect(unorderedRow.find('.bo-prod').text()).toBe('—')
    expect(unorderedRow.find('.bo-prod').classes()).toContain('bo-prod--none')
    expect(unorderedRow.find('.bo-qty--ordered').exists()).toBe(false)
  })
})

describe('buildSummaryTbody 逐 SKU 导出（FIX-3 / AC-12 同源）', () => {
  function mkRow(over: Record<string, unknown>): BeileOrderRow {
    return {
      id: 1,
      record_type: 'order',
      order_no: 'PO-900',
      order_date: '2026-08-19',
      customer: '客户',
      product_name: '产品',
      quantity: 0,
      factories: ['湖北'],
      items: [],
      ...over,
    } as unknown as BeileOrderRow
  }

  const tds = (tr: string) => [...tr.matchAll(/<td[^>]*>([\s\S]*?)<\/td>/g)].map((m) => m[1]!)
  const trsOf = (html: string) => html.split('<tr>').slice(1).map((s) => s.slice(0, s.indexOf('</tr>')))

  it('多 SKU：逐 SKU 订单数量 + 订单级「合计」行（= rowTotal），订单级列 rowspan=3', () => {
    const html = buildSummaryTbody([
      mkRow({
        is_ordered: false,
        items: [
          { id: 1, product_name: 'X', quantity: 10 },
          { id: 2, product_name: 'Y', quantity: 20 },
        ],
      }),
    ], '')

    const trs = trsOf(html)
    expect(trs.length).toBe(3)
    expect(html).toContain('rowspan="3"')

    const r1 = tds(trs[0]!)
    expect(r1[1]).toBe('PO-900') // 订单号列（订单级，由 rowspan 覆盖整单）
    expect(r1[5]).toBe('X')
    expect(r1[6]).toBe('10')
    expect(r1[7]).toBe('—')

    const r2 = tds(trs[1]!)
    expect(r2[0]).toBe('Y')
    expect(r2[1]).toBe('20')

    const r3 = tds(trs[2]!)
    expect(r3[0]).toBe('合计')
    expect(r3[1]).toBe('30')
    expect(r3[2]).toBe('—')
  })

  it('命中逐 SKU 快照（po_sku）：逐 SKU 显示实际下单量 + 生产量，合计 = rowTotal', () => {
    const html = buildSummaryTbody([
      mkRow({
        is_ordered: true,
        purchase_order_qty: 30,
        spare_quantity: 3,
        items: [
          { id: 1, product_name: 'X', quantity: 10, per_sku_source: 'po_sku', purchase_order_qty: 12, spare_quantity: 1 },
          { id: 2, product_name: 'Y', quantity: 20, per_sku_source: 'po_sku', purchase_order_qty: 18, spare_quantity: 2 },
        ],
      }),
    ], '')

    const trs = trsOf(html)
    const r1 = tds(trs[0]!)
    expect(r1[6]).toBe('12')
    expect(r1[7]).toBe('13') // 12 + 1
    const r2 = tds(trs[1]!)
    expect(r2[0]).toBe('Y')
    expect(r2[1]).toBe('18')
    expect(r2[2]).toBe('20') // 18 + 2
    const r3 = tds(trs[2]!)
    expect(r3[1]).toBe('30')
    expect(r3[2]).toBe('33') // 30 + 3
  })

  it('关键字筛选与页面同源：仅输出命中关键字的 SKU（filterVisibleSkus）', () => {
    const html = buildSummaryTbody([
      mkRow({
        is_ordered: false,
        items: [
          { id: 1, product_name: '不匹配品', quantity: 10 },
          { id: 2, product_name: '命中品', quantity: 20 },
        ],
      }),
    ], '命中品')

    const trs = trsOf(html)
    expect(trs.length).toBe(1) // 仅 1 个命中 SKU → 无合计行
    expect(html).toContain('命中品')
    expect(html).not.toContain('不匹配品')
  })

  it('单 SKU 已下单：订单数量取 purchase_order_qty、生产数量=订单+备品（无合计行）', () => {
    const html = buildSummaryTbody([
      mkRow({
        is_ordered: true,
        purchase_order_qty: 8,
        spare_quantity: 2,
        items: [{ id: 1, product_name: 'A', quantity: 10 }],
      }),
    ], '')

    const trs = trsOf(html)
    expect(trs.length).toBe(1)
    expect(html).not.toContain('合计')
    const cells = tds(trs[0]!)
    expect(cells[6]).toBe('8')
    expect(cells[7]).toBe('10')
  })
})