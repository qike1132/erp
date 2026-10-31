/**
 * /report 报表流水页改版的结构断言（与 /stock 对齐的方案 A）。
 *
 * 本机开不了浏览器预览，排版靠人眼实测；「单行工具条 / 表格无内盒 /
 * 列宽按比例 / 空值留白 / 数量列格式化」这些是结构事实，在此固化。
 *
 * 2026-10-06 增补：订单/备货流水行尾「操作」列（行内编辑/删除，权限门控）。
 *
 * 挂载按生产配置（unstyled + PT）—— 默认模式渲染出的 p-* 类名生产里不存在。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { nextTick, type Component } from 'vue'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import PrimeVue from 'primevue/config'
import { plushCutePT } from '@/styles/primevue-pt'

const mocks = vi.hoisted(() => ({
  orderLogsMock: vi.fn(),
  queryData: null as unknown as { value: unknown },
  hasPermission: vi.fn(() => true),
  hasAnyPermission: vi.fn((_c: string[]) => true),
}))

vi.mock('@/api', () => ({
  reportApi: {
    orderLogs: mocks.orderLogsMock,
    stockinLogs: vi.fn(),
    stockoutLogs: vi.fn(),
    deductionLogs: vi.fn(),
    returnLogs: vi.fn(),
  },
  // 报表行内操作链路（useReportRowActions → orderApi/stockApi/stockReturnApi）
  orderApi: {
    records: vi.fn(),
    detail: vi.fn(),
    update: vi.fn(),
    updateDeduct: vi.fn(),
    delete: vi.fn(),
    updateItem: vi.fn(),
    deleteItem: vi.fn(),
  },
  // 2026-10-07：出货/抵扣/退货行内操作链路（useReportRowActions）会用到
  stockApi: {
    stockoutRecords: vi.fn(),
    editStockout: vi.fn(),
    deleteStockout: vi.fn(),
  },
  stockReturnApi: {
    records: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  },
}))

vi.mock('@/stores/catalog', () => ({
  useCatalogStore: () => ({
    activeCustomerNames: [
      { id: 1, name: 'MINISO国际' },
      { id: 2, name: 'TOP TOY' },
    ],
    ensureActiveCustomerNames: vi.fn().mockResolvedValue(undefined),
  }),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    user: { factory: '' },
    hasPermission: mocks.hasPermission,
    hasAnyPermission: mocks.hasAnyPermission,
  }),
}))

vi.mock('@/composables/useConfirmDialog', () => ({
  useConfirmDialog: () => ({
    open: { value: false },
    text: { value: '' },
    sub: { value: '' },
    type: { value: 'danger' },
    onConfirm: vi.fn(),
    onCancel: vi.fn(),
    confirm: vi.fn(async () => true),
  }),
}))

vi.mock('@tanstack/vue-query', async () => {
  const { ref } = await import('vue')
  const dataRef = ref<unknown>(null)
  mocks.queryData = dataRef as { value: unknown }
  return {
    useQuery: () => ({
      data: dataRef,
      isLoading: ref(false),
      isFetching: ref(false),
      // ReportView 的 R40 错误横幅读 error（reportErrorMessage computed）——缺字段即
      // TypeError（该文件实测），mock 必须覆盖组件解构的全部字段
      error: ref(undefined),
      refetch: vi.fn(),
    }),
    // ReportView setup 链路（useReportRowActions → useOrderDetailEdit /
    // useOrderDelete / useApiMutation）创建时即调用，缺此导出 mock 挂载即抛错
    useQueryClient: () => ({ invalidateQueries: vi.fn() }),
    keepPreviousData: {},
  }
})

import ReportView from '@/views/report/ReportView.vue'
import ReportTabGroup from '@/views/report/components/ReportTabGroup.vue'
import ReportFilterBar from '@/views/report/components/ReportFilterBar.vue'
import ReportTable from '@/views/report/components/ReportTable.vue'
import UiDataTable from '@/components/ui/UiDataTable.vue'

// 每行一张「单 SKU 订单」（distinct order_id → 渲染成 3 个单 SKU 压一行）
const LOGS = [
  { id: 1, order_id: 101, item_id: 11, order_no: 'SO-001', order_date: '2026-09-29 14:32', customer: 'MINISO国际', product_name: '鲨鱼毛绒公仔-60cm', product_barcode: '6901', quantity: 15000, order_total_qty: 15000, item_count: 1, note: '客户临时补单' },
  { id: 2, order_id: 102, item_id: 12, order_no: 'SO-002', order_date: '2026-09-29 11:08', customer: 'TOP TOY', product_name: '鲨鱼毛绒公仔-60cm', product_barcode: '6901', quantity: 10000, order_total_qty: 10000, item_count: 1, note: '' },
  { id: 3, order_id: 103, item_id: 13, order_no: 'SO-003', order_date: '2026-09-28 16:45', customer: '网易严选', product_name: '咸鱼按摩捶-海盐蓝', product_barcode: '6902', quantity: 5000, order_total_qty: 5000, item_count: 1, note: '' },
]

const RESPONSE = { logs: LOGS, pagination: { total: 1284, pages: 86 } }

function mountView() {
  mocks.queryData.value = RESPONSE
  return mount(ReportView, {
    global: {
      plugins: [[PrimeVue, { unstyled: true, pt: plushCutePT }]],
      stubs: {
        // 弹窗与确认框不全量挂载：本文件锁表格结构，弹窗链路各自有专项测试
        EditOrderItemModal: true,
        EditStockinModal: true,
        EditStockoutModal: true,
        EditReturnModal: true,
        UiConfirmDialog: true,
      },
    },
  })
}

/**
 * 2026-10-23 起 /report 进页面自动查询（searched 门槛已移除）：挂载后表格即有数据，
 * 不再需要先点一次「查询」。
 */
async function mountViewWithData() {
  const wrapper = mountView()
  await nextTick()
  return wrapper
}

/** 订单流水的表格列（与 useReportConfig 的订单分支一致：八列、末列 9% 操作） */
const TABLE_COLUMNS = [
  { field: 'date', header: '下单时间', align: 'left' as const, width: '11%' },
  { field: 'no', header: '订单号', align: 'left' as const, width: '12%' },
  { field: 'customer', header: '客户', align: 'left' as const, width: '10%' },
  { field: 'product_name', header: '产品名称', align: 'left' as const, width: '33%' },
  { field: 'product_barcode', header: '条码', align: 'left' as const, width: '10%' },
  { field: 'quantity', header: '数量', align: 'center' as const, width: '8%', sortable: true },
  { field: 'note', header: '备注', align: 'left' as const, width: '7%' },
  { field: 'actions', header: '操作', align: 'center' as const, width: '9%' },
]

const ORDER_CFG = {
  label: '订单流水', endpoint: '/reports/order-logs', dateKey: 'order_date',
  countKey: 'order_count', dateLabel: '下单时间', countLabel: '数量', noteKey: 'note',
  noLabel: '订单号', noKey: 'order_no',
}
const STOCKIN_CFG = {
  label: '备货流水', endpoint: '/reports/stockin-logs', dateKey: 'stockin_date',
  countKey: 'stockin_count', dateLabel: '备货时间', countLabel: '备货数量', noteKey: 'note',
  noLabel: '备货单号', noKey: 'record_no',
}

/** ReportTable 单测挂载：不走 ReportView 的数据链路，直接锁表格结构与操作列行为 */
function mountTable(
  logs: Record<string, unknown>[],
  canManage: boolean,
  activeTab: 'order' | 'stockin' = 'order',
) {
  return mount(ReportTable, {
    props: {
      logs,
      columns: TABLE_COLUMNS,
      isLoading: false,
      isFetching: false,
      perPage: 15,
      pagination: { total: logs.length, pages: 1 },
      currentCfg: activeTab === 'order' ? ORDER_CFG : STOCKIN_CFG,
      activeTab,
      canEdit: canManage,
      canDelete: canManage,
    },
    global: { plugins: [[PrimeVue, { unstyled: true, pt: plushCutePT }]] },
  })
}

function mountTabs(over: Record<string, unknown> = {}) {
  return mount(ReportTabGroup, { props: { modelValue: 'order', ...over } })
}

function mountFilterBar(over: Record<string, unknown> = {}) {
  return mount(ReportFilterBar, {
    props: {
      filters: { customer: '', product: '' },
      customerOptions: [{ value: 'MINISO国际', label: 'MINISO国际' }],
      ...over,
    },
    global: { plugins: [[PrimeVue, { unstyled: true, pt: plushCutePT }]] },
  })
}

/**
 * 触发 UiDataTable 的排序事件。UiDataTable 是泛型 SFC，直接传入会让 findComponent
 * 的重载解析失败，故先擦成 Component 再收窄到「可 $emit」的形态。
 */
async function emitSort(w: VueWrapper, field: string, order: number) {
  const table = w.findComponent(UiDataTable as unknown as Component) as unknown as {
    vm: { $emit: (event: string, payload: unknown) => void }
  }
  table.vm.$emit('sort', { field, order })
  await nextTick()
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.hasPermission.mockReturnValue(true)
  mocks.hasAnyPermission.mockReturnValue(true)
})

describe('ReportTabGroup —— 维度 tab', () => {
  it('五个维度 tab 都在', () => {
    expect(mountTabs().text()).toContain('订单流水')
    expect(mountTabs().text()).toContain('备货流水')
    expect(mountTabs().text()).toContain('出货流水')
    expect(mountTabs().text()).toContain('备货抵扣')
    expect(mountTabs().text()).toContain('退货流水')
  })

  it('用系统的 UiTabs / UiTabTrigger，不自己写一套 tab 样式', () => {
    const w = mountTabs()

    expect(w.find('.ui-tab-group').exists()).toBe(true)
    expect(w.findAll('.ui-tab-btn')).toHaveLength(5)
  })

  it('当前 tab 为选中态，切换后跟着变', () => {
    expect(mountTabs().findAll('.ui-tab-btn')[0]?.classes()).toContain('active')
    expect(mountTabs({ modelValue: 'stockout' }).findAll('.ui-tab-btn')[2]?.classes()).toContain('active')
  })

  it('点击上抛 change', async () => {
    const w = mountTabs()

    // reka-ui 的 tab 触发器在 mousedown.left 上激活（不是 click），见 TabsTrigger.vue
    await w.findAll('.ui-tab-btn')[1]?.trigger('mousedown')

    expect(w.emitted('change')?.[0]).toEqual(['stockin'])
  })
})

describe('ReportFilterBar —— 系统控件与动作', () => {
  it('客户下拉与产品输入都用系统组件，查询/重置/导出 都在', () => {
    const w = mountFilterBar()

    expect(w.findComponent({ name: 'UiSelect' }).exists()).toBe(true)
    expect(w.findComponent({ name: 'UiInput' }).exists()).toBe(true)
    expect(w.find('[aria-label="查询"]').exists()).toBe(true)
    expect(w.find('[aria-label="重置"]').exists()).toBe(true)
    expect(w.find('[aria-label="导出"]').exists()).toBe(true)
  })

  it('日期区间筛选已移除（按反馈删除），连带不留空的日期控件', () => {
    const w = mountFilterBar()

    expect(w.findAllComponents({ name: 'UiDatePicker' })).toHaveLength(0)
  })

  it('字段名交给 placeholder，不再占一行常驻 label', () => {
    expect(mountFilterBar().findAll('label')).toHaveLength(0)
  })

  it('产品名输入写回 model（受控）', async () => {
    const w = mountFilterBar()

    await w.find('input[aria-label="产品名称 / SKU / 订单号"]').setValue('鲨鱼')

    expect((w.props('filters') as { product: string }).product).toBe('鲨鱼')
  })

  it('查询 / 重置 / 导出 各自上抛', async () => {
    const w = mountFilterBar()

    await w.find('[aria-label="查询"]').trigger('click')
    await w.find('[aria-label="重置"]').trigger('click')
    await w.find('[aria-label="导出"]').trigger('click')

    expect(w.emitted('search')).toHaveLength(1)
    expect(w.emitted('reset')).toHaveLength(1)
    expect(w.emitted('export')).toHaveLength(1)
  })
})

describe('ReportView —— 单行工具条', () => {
  it('工具条里有页面标题', () => {
    expect(mountView().find('.rp-toolbar h1').text()).toBe('报表流水')
  })

  it('tab 组、筛选、导出在同一行（同一工具条容器内）', async () => {
    const w = mountView()
    // 2026-10-23 起导出按钮常驻（查询门槛已移除），不再需要先点查询
    await flushPromises()

    expect(w.find('.rp-toolbar .rp-tab-group').exists()).toBe(true)
    expect(w.find('.rp-toolbar .rp-filter-bar').exists()).toBe(true)
    expect(w.find('.rp-toolbar [aria-label="导出"]').exists()).toBe(true)
  })

  it('不再有原来那个空着的卡片头（tab 原先独占一行）', () => {
    expect(mountView().find('.page-card-header').exists()).toBe(false)
  })
})

describe('ReportView —— 表格与数字格式', () => {
  it('订单流水八列按比例分配宽度（首列下单时间贴左、末列 9% 是操作列）', () => {
    const headers = mountView().findAll('th')
    const styles = headers.map((th) => th.attributes('style') ?? '')

    expect(styles[0]).toContain('11%')  // 下单时间
    expect(styles[1]).toContain('12%')  // 订单号
    expect(styles[2]).toContain('10%')  // 客户
    expect(styles[3]).toContain('33%')  // 产品名称（2026-10-31 加宽，避免显示不全）
    expect(styles[4]).toContain('10%')  // 条码
    expect(styles[5]).toContain('8%')   // 数量
    expect(styles[6]).toContain('7%')   // 备注
    expect(styles[7]).toContain('9%')   // 操作
  })

  it('数量走千分位并加粗', async () => {
    const cells = (await mountViewWithData()).findAll('tbody tr')[0]!.findAll('td')

    expect(cells[5]?.text()).toContain('15,000')
    expect(cells[5]?.find('.rp-qty').exists()).toBe(true)
  })

  it('空值留白，不显示「-」占位符', async () => {
    const cells = (await mountViewWithData()).findAll('tbody tr')[1]!.findAll('td')

    expect(cells[6]?.text()).toBe('')
  })

  it('数量列可排序（当前页客户端重排）', async () => {
    const w = await mountViewWithData()

    await emitSort(w, 'quantity', 1)
    expect(w.findAll('tbody tr')[0]?.text()).toContain('5,000')

    await emitSort(w, 'quantity', -1)
    expect(w.findAll('tbody tr')[0]?.text()).toContain('15,000')
  })
})

describe('ReportTable —— 订单流水多 SKU 跨行合并（方案 C）', () => {
  // 订单 201 两个 SKU（100 + 200），订单 202 单 SKU；order_total_qty/item_count 是
  // 后端仍会下发的订单级字段 —— 方案 C 刻意不再显示，故留在夹具里当「不该出现」的证据。
  const MULTI = [
    { order_id: 201, item_id: 21, order_no: 'SO-M1', order_date: '2026-10-13 09:12', customer: 'MINISO国际', product_name: '鲨鱼毛绒公仔-60cm', product_barcode: '6901', quantity: 100, order_total_qty: 300, item_count: 2, order_note: '整单备注', item_note: 'SKU-A备注', note: 'SKU-A备注' },
    { order_id: 201, item_id: 22, order_no: 'SO-M1', order_date: '2026-10-13 09:12', customer: 'MINISO国际', product_name: '企鹅玩偶-40cm', product_barcode: '6902', quantity: 200, order_total_qty: 300, item_count: 2, order_note: '整单备注', item_note: 'SKU-B备注', note: 'SKU-B备注' },
    { order_id: 202, item_id: 23, order_no: 'SO-M2', order_date: '2026-10-13 10:05', customer: 'TOP TOY', product_name: '小熊抱枕-35cm', product_barcode: '6903', quantity: 50, order_total_qty: 50, item_count: 1, order_note: '', item_note: '单行备注', note: '单行备注' },
  ]

  it('每个 SKU 各占一行、全部平铺（不再有折叠/母行/子行）', () => {
    const w = mountTable(MULTI, true)
    const rows = w.findAll('tbody tr')

    expect(rows).toHaveLength(3)
    expect(w.findAll('tr.parent-row')).toHaveLength(0)
    expect(w.findAll('tr.child-row')).toHaveLength(0)
    expect(w.find('.rp-tree').exists()).toBe(false)
  })

  it('同一订单的「时间/单号/客户」并成跨行格，产品/条码/数量/备注/操作逐行渲染', () => {
    const cells = mountTable(MULTI, true).findAll('tbody tr')[0]!.findAll('td')

    expect(cells).toHaveLength(8)
    expect(cells[0]!.attributes('rowspan')).toBe('2')  // 下单时间
    expect(cells[1]!.attributes('rowspan')).toBe('2')  // 订单号
    expect(cells[2]!.attributes('rowspan')).toBe('2')  // 客户
    expect(cells[3]!.attributes('rowspan')).toBeUndefined()  // 产品名称
    expect(cells[4]!.attributes('rowspan')).toBeUndefined()  // 条码
    expect(cells[5]!.attributes('rowspan')).toBeUndefined()  // 数量
    expect(cells[6]!.attributes('rowspan')).toBeUndefined()  // 备注
    expect(cells[7]!.attributes('rowspan')).toBeUndefined()  // 操作
    // 合并格里显示的是订单级取值
    expect(cells[0]!.text()).toBe('2026-10-13 09:12')
    expect(cells[1]!.text()).toBe('SO-M1')
    expect(cells[2]!.text()).toBe('MINISO国际')
  })

  it('组内第 2 行只剩非合并的 5 格，且内容是该 SKU 自己的', () => {
    const cells = mountTable(MULTI, true).findAll('tbody tr')[1]!.findAll('td')

    expect(cells).toHaveLength(5)
    expect(cells[0]!.text()).toBe('企鹅玩偶-40cm')
    expect(cells[1]!.text()).toBe('6902')
    expect(cells[2]!.text()).toBe('200')
    expect(cells[3]!.text()).toBe('SKU-B备注')
  })

  it('单 SKU 订单的三列自己渲染（跨度为 1，PrimeVue 不输出 rowspan）', () => {
    const cells = mountTable(MULTI, true).findAll('tbody tr')[2]!.findAll('td')

    expect(cells).toHaveLength(8)
    expect(['1', undefined]).toContain(cells[0]!.attributes('rowspan'))
    expect(cells[0]!.text()).toBe('2026-10-13 10:05')
    expect(cells[1]!.text()).toBe('SO-M2')
    expect(cells[2]!.text()).toBe('TOP TOY')
  })

  it('相邻两张不同订单即使客户/时间相同也不合并（合并键是订单，不是显示值）', () => {
    const SAME = [
      { order_id: 301, item_id: 31, order_no: 'SO-X1', order_date: '2026-10-13 09:00', customer: '同名客户', product_name: '甲产品', product_barcode: '6901', quantity: 1, note: '' },
      { order_id: 302, item_id: 32, order_no: 'SO-X2', order_date: '2026-10-13 09:00', customer: '同名客户', product_name: '乙产品', product_barcode: '6902', quantity: 2, note: '' },
    ]
    const w = mountTable(SAME, false)
    const rows = w.findAll('tbody tr')

    // 各 1 个 SKU、客户与时间完全同名：仍必须是两行各自完整渲染，
    // 不能把客户/时间并成一个跨两行的格（拿显示值当合并键就会犯这个错）
    expect(rows).toHaveLength(2)
    expect(rows[0]!.findAll('td')).toHaveLength(8)
    expect(rows[1]!.findAll('td')).toHaveLength(8)
    expect(rows[0]!.findAll('td')[1]!.text()).toBe('SO-X1')
    expect(rows[1]!.findAll('td')[1]!.text()).toBe('SO-X2')
  })

  it('数量列是各 SKU 自己的数量：整单合计与「共 N 个 SKU」都不再出现', () => {
    const w = mountTable(MULTI, true)
    const qty = w.findAll('tbody tr').map((r) => r.find('.rp-qty').text())

    expect(qty).toEqual(['100', '200', '50'])
    expect(w.text()).not.toContain('300')          // 订单 201 的整单合计
    expect(w.text()).not.toContain('共 2 个 SKU')  // 原来的母行摘要
  })

  it('备注列逐行显示各自 SKU 备注（订单级备注不进表格）', () => {
    const w = mountTable(MULTI, true)

    expect(w.findAll('tbody tr').map((r) => r.find('.rp-note').text()))
      .toEqual(['SKU-A备注', 'SKU-B备注', '单行备注'])
    expect(w.text()).not.toContain('整单备注')
  })

  it('每一行（含组内后续行）都挂操作按钮：按钮只作用于具体 SKU', () => {
    const rows = mountTable(MULTI, true).findAll('tbody tr')

    for (const tr of rows) {
      expect(tr.find('.rp-btn-edit').exists()).toBe(true)
      expect(tr.find('.rp-btn-danger').exists()).toBe(true)
    }
  })

  it('其余 tab（备货流水）不做行合并：每行都渲染完整八格', () => {
    const STOCKIN = [
      { record_id: 1, record_no: 'BH-1', stockin_date: '2026-10-13 09:00', customer: 'MINISO国际', product_name: '甲', product_barcode: '6901', quantity: 10, note: '' },
      { record_id: 2, record_no: 'BH-2', stockin_date: '2026-10-13 09:00', customer: 'MINISO国际', product_name: '乙', product_barcode: '6902', quantity: 20, note: '' },
    ]
    const rows = mountTable(STOCKIN, false, 'stockin').findAll('tbody tr')

    expect(rows).toHaveLength(2)
    for (const tr of rows) expect(tr.findAll('td')).toHaveLength(8)
  })

  it('首列「时间」左对齐（内容贴住左边框，参照 /stock 客户列）', async () => {
    const { useReportConfig } = await import('@/views/report/composables/useReportConfig')
    const { ref } = await import('vue')
    for (const tab of ['order', 'stockin', 'stockout', 'deduction', 'return'] as const) {
      const cols = useReportConfig(ref(tab), ref(true)).reportColumns.value
      expect(cols.find((c) => c.field === 'date')!.align).toBe('left')
    }
  })
})

describe('ReportTable —— 行内操作列（订单/备货流水）', () => {
  it('有权限：每行渲染编辑与删除按钮', () => {
    const w = mountTable(LOGS, true)

    const rows = w.findAll('tbody tr')
    expect(rows.length).toBe(3)
    for (const tr of rows) {
      expect(tr.find('.rp-btn-edit').exists()).toBe(true)
      expect(tr.find('.rp-btn-danger').exists()).toBe(true)
    }
  })

  it('点击按钮上抛原始行对象（row-edit / row-delete）', async () => {
    const w = mountTable(LOGS, true)

    await w.findAll('tbody tr')[0]!.find('.rp-btn-edit').trigger('click')
    await w.findAll('tbody tr')[1]!.find('.rp-btn-danger').trigger('click')

    const editPayload = w.emitted('row-edit')?.[0]?.[0] as Record<string, unknown>
    const deletePayload = w.emitted('row-delete')?.[0]?.[0] as Record<string, unknown>
    expect(editPayload.id).toBe(1)
    expect(editPayload.product_name).toBe('鲨鱼毛绒公仔-60cm')
    expect(deletePayload.id).toBe(2)
  })

  it('无权限：不渲染操作按钮（空单元格，不做「—」占位）', () => {
    const w = mountTable(LOGS, false)

    expect(w.findAll('.rp-btn-edit').length).toBe(0)
    expect(w.findAll('.rp-btn-danger').length).toBe(0)
  })

  it('五个维度：有权限末列是操作列，无权限整列不渲染（列定义由 useReportConfig 决定）', async () => {
    const { useReportConfig } = await import('@/views/report/composables/useReportConfig')
    const { ref } = await import('vue')
    const ALL = ['order', 'stockin', 'stockout', 'deduction', 'return'] as const
    // 有权限（2026-10-13）：五个维度都在末列追加 9% 操作列
    for (const tab of ALL) {
      const cols = useReportConfig(ref(tab), ref(true)).reportColumns.value
      expect(cols.at(-1)).toEqual({ field: 'actions', header: '操作', align: 'center', width: '9%' })
    }
    // 无权限：整列不渲染（连表头一起），不留空壳
    for (const tab of ALL) {
      const cols = useReportConfig(ref(tab), ref(false)).reportColumns.value
      expect(cols.some((c) => c.field === 'actions')).toBe(false)
    }
  })

  it('列定义：单号列 + 条码列都在、无状态列；五个 tab 共用同一套列（无独立展开列）', async () => {
    const { useReportConfig } = await import('@/views/report/composables/useReportConfig')
    const { ref } = await import('vue')

    const orderCols = useReportConfig(ref('order'), ref(true)).reportColumns.value
    expect(orderCols.map((c) => c.field)).toEqual(
      ['date', 'no', 'customer', 'product_name', 'product_barcode', 'quantity', 'note', 'actions'])
    expect(orderCols.find((c) => c.field === 'no')!.header).toBe('订单号')
    // 订单流水不再有独立的「展开」列（子行树线挪进「时间」列，2026-10-13 v2）
    expect(orderCols.some((c) => c.field === 'expand')).toBe(false)

    const stockinCols = useReportConfig(ref('stockin'), ref(true)).reportColumns.value
    expect(stockinCols.some((c) => c.field === 'expand')).toBe(false)
    expect(stockinCols.find((c) => c.field === 'product_barcode')!.header).toBe('条码')
    // 末列由「状态」改「备注」：不再有状态列
    expect(stockinCols.some((c) => c.field === 'status')).toBe(false)

    // 2026-10-13：五个 tab 的「单号」列头统一为「订单号」（用户要求；列里的值仍是各自的 备货/出货/退货单号）
    for (const tab of ['order', 'stockin', 'stockout', 'deduction', 'return'] as const) {
      const cols = useReportConfig(ref(tab), ref(true)).reportColumns.value
      expect(cols.find((c) => c.field === 'no')!.header).toBe('订单号')
    }
  })

  it('ReportView 的门控跟随 authStore.hasAnyPermission（含 manage 兜底镜像）', async () => {
    mocks.hasAnyPermission.mockReturnValue(false)
    const w = mountView()
    expect(w.findAll('.rp-btn-edit').length).toBe(0)
    expect(w.findAll('.rp-btn-danger').length).toBe(0)

    mocks.hasAnyPermission.mockReturnValue(true)
  })
})
