/**
 * QA 对抗性验证（前端）：
 * - F. SummaryModal.vue「为过 gate 压缩订单级 <td>」后的渲染等价性：
 *    * 表头 9 列、第 7 列为「损耗率」
 *    * 第 1 个 fabric 行的 3 个订单级单元格带 rowspan=N；后续行不再出现订单级单元格
 *    * 合计行 = colspan3 合计 + colspan3 + 损耗率空列 + 第8列数量合计 + 单位空列
 * - G. 导出/打印同源（AC-12）：SUMMARY_HEADERS 列数 == 数据行逻辑列数
 *    （用 rowspan/colspan 网格模拟逐行校验），订单数量取 purchase_order_qty、
 *    生产数量 = 订单数量 + 备品数量（备品数量独立列已删除）、未下单生产数量为「—」
 * - D2①. useSummaryModal：edits.length===0 早退已修（仅改损耗率也能保存）
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref, nextTick, defineComponent, h } from 'vue'

const mocks = vi.hoisted(() => ({
  beileListMock: vi.fn(),
  confirmBeileOrderMock: vi.fn(),
  confirmBeileStockinMock: vi.fn(),
  refetchMock: vi.fn(),
  setQueryDataMock: vi.fn(),
  queryData: null as unknown as ReturnType<typeof ref<unknown>>,
  downloadXlsMock: vi.fn(),
  printHtmlMock: vi.fn(),
  hasPermissionMock: vi.fn((_code: string) => true),
  saveFactoryEditsMock: vi.fn(),
}))

vi.mock('@/api', () => ({
  orderApi: {
    beileList: mocks.beileListMock,
    confirmBeileOrder: mocks.confirmBeileOrderMock,
    confirmBeileStockin: mocks.confirmBeileStockinMock,
  },
  purchaseApi: {
    orders: vi.fn(),
    unprocessedOrders: vi.fn(),
    factorySummary: vi.fn(),
    supplierSummary: vi.fn(),
    saveFactoryEdits: mocks.saveFactoryEditsMock,
    supplierSummaryExport: vi.fn(),
  },
}))

vi.mock('@/api/request', () => ({
  resolveStaticUrl: (url: string | null | undefined) => url ?? '',
}))

vi.mock('@tanstack/vue-query', async () => {
  const { ref: r } = await import('vue')
  const dataRef = r<unknown>(null)
  mocks.queryData = dataRef
  return {
    useQuery: () => ({ data: dataRef, isLoading: r(false), isFetching: r(false), refetch: mocks.refetchMock }),
    useQueryClient: () => ({ setQueryData: mocks.setQueryDataMock }),
    keepPreviousData: {},
  }
})

vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }) }))

vi.mock('@/composables/useToast', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
  showToast: vi.fn(),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ hasPermission: mocks.hasPermissionMock }),
}))

vi.mock('@/utils/xls', () => ({ downloadXls: mocks.downloadXlsMock }))
vi.mock('@/utils/print', () => ({ printHtml: mocks.printHtmlMock }))

import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils'
import HubeiView from '@/views/hubei/HubeiView.vue'
import BeileOrderRow from '@/views/beile-order/components/BeileOrderRow.vue'
import { provideBeileOrders, NOT_ORDERED_TIP, NOT_ORDERED_TOAST } from '@/views/beile-order/composables/useBeileOrders'
import type { BeileOrderRow as BeileOrderRowType } from '@/views/beile-order/composables/useBeileOrders'
import { toast } from '@/composables/useToast'
import SummaryModal from '@/views/purchase/components/SummaryModal.vue'
import { useSummaryModal } from '@/views/purchase/composables/useSummaryModal'
import type { FactorySummaryData } from '@/views/purchase/composables/useSummaryModal'
import type { OrderListApiResponse } from '@/api/order'
import { purchaseApi } from '@/api'

/**
 * 测试卫生：HubeiView 页头含 v-if 动态节点（未确认提醒横幅）。
 * 若组件树在测试结束后未卸载，其异步更新会在**后续测试**执行期间触发子组件
 * 重新 mount —— 此时 VTU 的 stub 拦截已失效，会实例化真实的 HubeiSearchBar
 * （其 setup 依赖 active pinia）并抛出 unhandled rejection。
 * 故统一在 afterEach 卸载，消除跨测试的异步残留更新。
 */
enableAutoUnmount(afterEach)

// ---------------- 通用：按 rowspan/colspan 网格模拟，逐行校验逻辑列数 ----------------
/**
 * 返回每一行的「逻辑列数」。逻辑列数 = 该行被填充的列位总数
 * （含被上方 rowspan 覆盖的列 + 本行 colspan 展开列）。
 * 一个结构自洽的表格：每行逻辑列数应等于表头列数。
 */
function logicalWidths(rows: Element[], nCols: number): number[] {
  const carry = new Array<number>(nCols).fill(0)
  const widths: number[] = []
  for (const tr of rows) {
    const filled = new Array<boolean>(nCols).fill(false)
    for (let c = 0; c < nCols; c++) if ((carry[c] ?? 0) > 0) filled[c] = true
    const newCarry = new Array<number>(nCols).fill(0)
    let col = 0
    for (const td of Array.from(tr.querySelectorAll('td'))) {
      while (col < nCols && filled[col]) col++
      const colspan = Number(td.getAttribute('colspan')) || 1
      const rowspan = Number(td.getAttribute('rowspan')) || 1
      for (let c = 0; c < colspan && col + c < nCols; c++) {
        filled[col + c] = true
        if (rowspan > 1) newCarry[col + c] = rowspan - 1
      }
      col += colspan
    }
    widths.push(filled.filter(Boolean).length)
    for (let c = 0; c < nCols; c++) {
      const prev = carry[c] ?? 0
      const next = newCarry[c] ?? 0
      carry[c] = Math.max(prev > 0 ? prev - 1 : 0, next)
    }
  }
  return widths
}

// =========================================================================
// F. SummaryModal 渲染等价性
// =========================================================================
describe('F. SummaryModal 订单级 <td> 压缩后的渲染等价性', () => {
  const factoryData: FactorySummaryData = {
    success: true,
    order_count: 2,
    groups: [
      {
        customer_name: '客户A',
        product_name: '产品1',
        product_quantity: 100,
        suppliers: [
          {
            supplier_name: '供应商1',
            fabrics: [
              { fabric_name: '布料A1', specification: 'S1', quantity: 10, unit: '米' },
              { fabric_name: '布料A2', specification: 'S2', quantity: 20, unit: '米' },
            ],
          },
          {
            supplier_name: '供应商2',
            fabrics: [{ fabric_name: '布料B1', specification: 'S3', quantity: 5, unit: '米' }],
          },
        ],
      },
      {
        customer_name: '客户B',
        product_name: '产品2',
        order_quantity: 50,
        suppliers: [
          { supplier_name: '供应商3', fabrics: [{ fabric_name: '布料C1', specification: 'S4', quantity: 7, unit: '米' }] },
        ],
      },
    ],
  }

  function mountModal() {
    return mount(SummaryModal, {
      props: { open: true, factoryData, supplierData: null, editMode: false, lossRate: 5, orderCount: 2, supplierGroups: [] },
      global: { stubs: { UiDialog: { template: '<div class="ui-dialog-stub"><slot name="title" /><slot /></div>' } } },
    })
  }

  it('表头 10 列：第 4 列为「备品数量」、第 8 列为「损耗率」', () => {
    const wrapper = mountModal()
    const headers = wrapper.findAll('thead th').map((th) => th.text())
    expect(headers).toHaveLength(10)
    expect(headers[3]).toBe('备品数量')
    expect(headers[7]).toBe('损耗率')
  })

  it('表头列数 == 每一行数据行的逻辑列数（网格自洽）', () => {
    const wrapper = mountModal()
    const nCols = wrapper.findAll('thead th').length
    const rows = wrapper.findAll('tbody tr').map((r) => r.element)
    const widths = logicalWidths(rows, nCols)
    expect(widths.every((w) => w === nCols)).toBe(true)
  })

  it('第 1 个 fabric 行的 4 个订单级单元格带 rowspan=3、供应商单元格 rowspan=2；后续行不再出现订单级单元格', () => {
    const wrapper = mountModal()
    const rows = wrapper.findAll('tbody tr')
    const row0 = rows[0]!.findAll('td')
    expect(row0).toHaveLength(10)
    // 4 个订单级单元格：客户 / 产品名称 / 订单数量 / 备品数量
    for (let i = 0; i < 4; i++) {
      expect(row0[i]!.attributes('rowspan')).toBe('3')
    }
    // 供应商单元格：供应商1 有 2 个 fabric → rowspan=2
    expect(row0[4]!.attributes('rowspan')).toBe('2')
    expect(row0[5]!.text()).toBe('布料A1')

    // 第 2 个 fabric 行（同供应商1 的第 2 条）：不应再出现订单级单元格
    const row1 = rows[1]!.findAll('td')
    expect(row1).toHaveLength(5) // 布料名称/规格型号/损耗率/数量/单位
    expect(row1.some((td) => td.attributes('rowspan') !== undefined)).toBe(false)
    expect(row1.map((td) => td.text()).join('|')).not.toContain('客户A')

    // 第 3 个 fabric 行（供应商2 首行）：供应商 rowspan=1 + 布料/规格/损耗率/数量/单位
    const row2 = rows[2]!.findAll('td')
    expect(row2).toHaveLength(6)
    expect(row2[0]!.attributes('rowspan')).toBe('1')
  })

  it('表格内已无「合计」行：末行是数据行，数量列仍按派生值', () => {
    const wrapper = mountModal()
    const rows = wrapper.findAll('tbody tr')
    // 末行不再是合计行（首格文本不是「合计」）
    expect(rows[rows.length - 1]!.findAll('td')[0]!.text()).not.toBe('合计')
    // 数量列仍为损耗率派生值：10 × 1.005 = 10.05 → 11（第 9 列；第 4 列为新增的备品数量）
    expect(rows[0]!.findAll('td')[8]!.text()).toBe('11')
  })
})

// =========================================================================
// D2①. useSummaryModal：仅改损耗率（edits 为空）也必须保存
// =========================================================================
describe('D2①. useSummaryModal 仅交互损耗率也能保存（edits.length===0 早退已修）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(purchaseApi.factorySummary).mockResolvedValue({
      success: true,
      order_count: 1,
      groups: [],
    } as never)
    vi.mocked(purchaseApi.supplierSummary).mockResolvedValue({ success: true, materials: [] } as never)
    mocks.saveFactoryEditsMock.mockResolvedValue({ success: true } as never)
  })

  it('openSummary + applyLossRate(50) + saveFactoryEdits → 调用 purchaseApi.saveFactoryEdits([], 50, orderIds)', async () => {
    const m = useSummaryModal()
    await m.openSummary([601, 602])
    m.applyLossRate(50)
    await m.saveFactoryEdits()

    expect(mocks.saveFactoryEditsMock).toHaveBeenCalledTimes(1)
    const [editsArg, rateArg, idsArg] = mocks.saveFactoryEditsMock.mock.calls[0]!
    expect(editsArg).toEqual([])
    expect(rateArg).toBe(50)
    expect(idsArg).toEqual([601, 602])
  })
})

// =========================================================================
// G. 导出/打印同源（AC-12）
// =========================================================================
const stubs = {
  UiSpinner: { template: '<span class="ui-spinner-stub" />' },
  UiPagination: { template: '<div class="ui-pagination-stub" />' },
  UiButton: { template: '<button type="button"><slot /></button>' },
  HubeiSearchBar: { template: '<div class="hu-search-stub" />' },
  VirtualList: {
    props: ['items'],
    methods: { scrollToTop() {} },
    template: '<div class="vl-stub"><div v-for="item in items" :key="item.id" class="vl-row"><slot :item="item" /></div></div>',
  },
}

/** HubeiView 自身 provide 状态实例；导出/打印按钮位于其页头右上角 */
const TestHost = defineComponent({
  setup() {
    return () => h(HubeiView)
  },
})

function makeListResponse(overrides: Partial<OrderListApiResponse> = {}): OrderListApiResponse {
  return {
    success: true, total: 1, page: 1, per_page: 18, unconfirmed_count: 1,
    data: [
      {
        id: 101, record_type: 'order', confirmed: true, confirmed_at: '2026-08-12T10:00:00', confirmed_by: 'admin',
        order_no: 'PO-101', customer: '已下单客户', order_date: '2026-08-12', product_name: '产品A', product_id: 1,
        quantity: 10, deduct_quantity: 0, deduct_stock: false, note: '', status: '待备货', factories: ['湖北'],
        items: [{ id: 1, product_name: '产品A', product_barcode: '690001', quantity: 10, note: '' }],
        is_ordered: true, purchase_order_qty: 8, spare_quantity: 2, spare_rate: 5,
      },
    ],
    ...overrides,
  } as OrderListApiResponse
}

async function mountTab() {
  const wrapper = mount(TestHost, { global: { stubs } })
  await flushPromises()
  await nextTick()
  return wrapper
}

describe('G. 导出/打印同源（AC-12）：表头列数 == 数据行逻辑列数', () => {
  beforeEach(() => {
    mocks.downloadXlsMock.mockReset()
    mocks.hasPermissionMock.mockReset()
    mocks.hasPermissionMock.mockReturnValue(true)
    mocks.queryData.value = makeListResponse()
  })

  it('单 SKU：表头 10 列 == 数据行 10 个 td；订单数量列 = purchase_order_qty；生产数量列 = 订单数量+备品数量（无备品列）；小义开单列 = 已开单', async () => {
    const wrapper = await mountTab()
    await wrapper.find('.bo-toolbar-btn--export').trigger('click')
    await flushPromises()

    const [html] = mocks.downloadXlsMock.mock.calls[0]!
    const doc = new DOMParser().parseFromString(html, 'text/html')
    const nCols = doc.querySelectorAll('thead th').length
    expect(nCols).toBe(10)
    // 备品数量独立列已删除：导出表头不得再出现
    expect(Array.from(doc.querySelectorAll('thead th')).map((th) => th.textContent).join('|')).not.toContain('备品数量')

    const dataRows = Array.from(doc.querySelectorAll('tbody tr'))
    const widths = logicalWidths(dataRows, nCols)
    expect(widths.every((w) => w === nCols)).toBe(true)

    const cells = Array.from(dataRows[0]!.querySelectorAll('td')).map((td) => td.textContent || '')
    expect(cells[1]).toBe('PO-101')   // 订单号（2026-09-29 恢复，紧随订单类型）
    expect(cells[6]).toBe('8')        // 订单数量 = purchase_order_qty（新口径）
    expect(cells[7]).toBe('10')       // 生产数量 = 订单数量 + 备品数量 = 8 + 2
    expect(cells[8]).toBe('已开单')    // 小义开单 = 已开单（is_ordered=true）
  })

  it('多 SKU + 未下单：逐 SKU 输出订单数量（各 SKU 自身）；生产数量为「—」、小义开单为「未开单」', async () => {
    mocks.queryData.value = makeListResponse({
      total: 2,
      data: [
        {
          id: 102, record_type: 'order', confirmed: true, confirmed_at: null, confirmed_by: null,
          order_no: 'PO-102', customer: '未下单客户', order_date: '2026-08-11', product_name: '产品B', product_id: 2,
          quantity: 30, deduct_quantity: 0, deduct_stock: false, note: '', status: '待备货', factories: ['湖北'],
          items: [
            { id: 2, product_name: '产品B', product_barcode: '690002', quantity: 10, note: '' },
            { id: 3, product_name: '产品B2', product_barcode: '690003', quantity: 20, note: '' },
          ],
          is_ordered: false, purchase_order_qty: 0, spare_quantity: 0,
        },
      ] as unknown as OrderListApiResponse['data'],
    })
    const wrapper = await mountTab()
    await wrapper.find('.bo-toolbar-btn--export').trigger('click')
    await flushPromises()

    const [html] = mocks.downloadXlsMock.mock.calls[0]!
    const doc = new DOMParser().parseFromString(html, 'text/html')
    const nCols = doc.querySelectorAll('thead th').length
    expect(nCols).toBe(10)

    const rows = Array.from(doc.querySelectorAll('tbody tr'))
    // 逐 SKU 2 行（不再追加「合计」行）；每行逻辑列数 == 表头 10 列（rowspan 网格自洽）
    expect(rows.length).toBe(2)
    const widths = logicalWidths(rows, nCols)
    expect(widths.every((w) => w === nCols)).toBe(true)

    // 首行（SKU 产品B）：订单级 5 列 + 产品名称/订单数量/生产数量/小义开单 + 备注 = 10 td
    const firstCells = Array.from(rows[0]!.querySelectorAll('td'))
    expect(firstCells.length).toBe(10)
    expect(firstCells[1]!.textContent).toBe('PO-102')  // 订单号（订单级，rowspan 覆盖整单）
    expect(firstCells[5]!.textContent).toBe('产品B')
    expect(firstCells[6]!.textContent).toBe('10')   // 逐 SKU 订单数量（该 SKU 自身）
    expect(firstCells[7]!.textContent).toBe('—')    // 未下单生产数量 → 「—」
    expect(firstCells[8]!.textContent).toBe('未开单')
    // 订单级「小义开单」列 rowspan=2（跨 2 SKU 行）
    expect(firstCells[8]!.getAttribute('rowspan')).toBe('2')

    // 第 2 行（SKU 产品B2）：仅 产品名称/订单数量/生产数量/备注 = 4 td（订单级列由 rowspan 覆盖）
    const secondCells = Array.from(rows[1]!.querySelectorAll('td'))
    expect(secondCells.length).toBe(4)
    expect(secondCells[0]!.textContent).toBe('产品B2')
    expect(secondCells[1]!.textContent).toBe('20')
    expect(secondCells[2]!.textContent).toBe('—')
  })
})

// =========================================================================
// CR-1. 前端展示收敛：未下单警示仅在「未确认 且 未下单」生效
// =========================================================================
function baseRow(extra: Record<string, unknown> = {}): BeileOrderRowType {
  return {
    id: 1, record_type: 'order', order_no: 'PO-1', customer: 'C1', order_date: '2026-09-01',
    product_name: '产品A', product_id: 1, quantity: 10, deduct_quantity: 0, deduct_stock: false,
    note: '', status: '', factories: ['湖北'],
    items: [{ id: 1, product_name: '产品A', product_barcode: '690001', quantity: 10, note: '' }],
    ...extra,
  } as unknown as BeileOrderRowType
}

function mountRow(item: BeileOrderRowType) {
  return mount(BeileOrderRow, {
    props: {
      item, confirmStatus: 'unconfirmed', isConfirming: false,
      highlightId: null, confirmable: true, selectable: false, selected: false,
    },
    global: { stubs: { UiCheckbox: true } },
  })
}

describe('CR-1. BeileOrderRow 展示收敛（未下单警示仅对「未确认 且 未下单」生效）', () => {
  it('未确认 + 未下单 → 「小义开单」警示态「未开单」+ tooltip；数量走原口径；按钮 disabled + tooltip；生产数量「—」', () => {
    const wrapper = mountRow(baseRow({ confirmed: false, is_ordered: false, quantity: 10 }))
    // 「小义开单」：未确认 且 未开单 → 警示色 --pending + tooltip
    const badge = wrapper.find('.bo-open-badge--pending')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toBe('未开单')
    expect(badge.attributes('title')).toBe(NOT_ORDERED_TIP)
    expect(wrapper.find('.bo-open-badge--done').exists()).toBe(false)
    expect(wrapper.find('.bo-open-badge--muted').exists()).toBe(false)

    // 订单数量（订单级汇总）：纯数字原口径 10，不加粗
    expect(wrapper.find('.bo-qty').text()).toBe('10')
    expect(wrapper.find('.bo-qty--ordered').exists()).toBe(false)

    const btn = wrapper.find('button.bo-confirm-btn')
    expect(btn.exists()).toBe(true)
    expect(btn.attributes('disabled')).toBeDefined()
    expect(btn.attributes('title')).toBe(NOT_ORDERED_TOAST)

    // 生产数量：未下单 → 「—」
    expect(wrapper.find('.bo-prod').text()).toBe('—')
    expect(wrapper.find('.bo-prod').classes()).toContain('bo-prod--none')
  })

  it('已确认 + 未下单（历史行）→ 小义开单仅中性灰「未开单」，无警示态、无 tooltip、无确认按钮（CR-1 守卫生效）', () => {
    const wrapper = mountRow(baseRow({ confirmed: true, is_ordered: false, quantity: 10 }))
    // CR-1 守卫：已确认历史行不得出现警示色「未开单」
    expect(wrapper.find('.bo-open-badge--pending').exists()).toBe(false)
    expect(wrapper.find('.bo-open-badge--done').exists()).toBe(false)
    // 事实照实呈现：未开单，但用中性灰 --muted
    const muted = wrapper.find('.bo-open-badge--muted')
    expect(muted.exists()).toBe(true)
    expect(muted.text()).toBe('未开单')
    // 中性态不得带任何 tooltip；全局不得出现「未下单」警示 tooltip
    expect(muted.attributes('title')).toBeUndefined()
    expect(wrapper.find(`[title="${NOT_ORDERED_TIP}"]`).exists()).toBe(false)
    // 数量无徽章、走历史行原口径 10；生产数量「—」
    expect(wrapper.find('.bo-qty').text()).toBe('10')
    expect(wrapper.find('.bo-prod').text()).toBe('—')
    // 无确认按钮（已确认走 v-else 徽章分支）
    expect(wrapper.find('button.bo-confirm-btn').exists()).toBe(false)
    expect(wrapper.findAll('.bo-confirm-badge--done').length).toBeGreaterThanOrEqual(1)
  })

  it('未确认 + 已下单 → 「小义开单」成功态「已开单」+ 数量=purchase_order_qty + 生产数量=订单+备品 + 按钮可点', () => {
    const wrapper = mountRow(baseRow({
      confirmed: false, is_ordered: true, quantity: 10, purchase_order_qty: 8, spare_quantity: 2,
    }))
    const done = wrapper.find('.bo-open-badge--done')
    expect(done.exists()).toBe(true)
    expect(done.text()).toBe('已开单')
    expect(done.attributes('title')).toBeUndefined()
    expect(wrapper.find('.bo-open-badge--pending').exists()).toBe(false)
    expect(wrapper.find('.bo-open-badge--muted').exists()).toBe(false)
    expect(wrapper.find('.bo-qty--ordered').text()).toBe('8')
    // 生产数量 = 订单数量 + 备品数量 = 8 + 2 = 10（备品独立列已删除，仅保留计算结果）
    expect(wrapper.find('.bo-prod').text()).toBe('10')
    const btn = wrapper.find('button.bo-confirm-btn')
    expect(btn.exists()).toBe(true)
    expect(btn.attributes('disabled')).toBeUndefined()
  })
})

// =========================================================================
// CR-1. 前端确认门控收敛（useBeileOrders.handleConfirm）
// =========================================================================
function makeHandleHost() {
  let handle: ReturnType<typeof provideBeileOrders> | null = null
  const Host = defineComponent({
    setup() {
      handle = provideBeileOrders()
      return () => h('div')
    },
  })
  const wrapper = mount(Host, { global: { stubs } })
  return { wrapper, get: () => handle! }
}

describe('CR-1. handleConfirm 门控收敛：仅「未确认 且 未下单」toast 拦截', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.queryData.value = makeListResponse()
  })

  it('未确认 + 未下单 → toast(NOT_ORDERED_TOAST)，不发确认请求', async () => {
    const { get } = makeHandleHost()
    await get().handleConfirm(baseRow({ id: 201, confirmed: false, is_ordered: false }))
    expect(toast.error).toHaveBeenCalledWith(NOT_ORDERED_TOAST)
    expect(mocks.confirmBeileOrderMock).not.toHaveBeenCalled()
  })

  it('已确认 + 未下单（历史行）→ 早退，不 toast 也不发请求', async () => {
    const { get } = makeHandleHost()
    await get().handleConfirm(baseRow({ id: 202, confirmed: true, is_ordered: false }))
    expect(toast.error).not.toHaveBeenCalled()
    expect(mocks.confirmBeileOrderMock).not.toHaveBeenCalled()
  })

  it('未确认 + 已下单 → 放行，调用确认接口', async () => {
    mocks.confirmBeileOrderMock.mockResolvedValue({ success: true, message: '订单已确认' })
    const { get } = makeHandleHost()
    await get().handleConfirm(baseRow({ id: 203, confirmed: false, is_ordered: true }))
    expect(mocks.confirmBeileOrderMock).toHaveBeenCalledWith(203)
    expect(toast.error).not.toHaveBeenCalled()
  })
})
