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
import { mount, type VueWrapper } from '@vue/test-utils'
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
  // 报表行还原链路（useReportRowActions → useOrderDetailEdit/useOrderDelete）会用到
  orderApi: {
    records: vi.fn(),
    detail: vi.fn(),
    update: vi.fn(),
    updateDeduct: vi.fn(),
    delete: vi.fn(),
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

const LOGS = [
  { id: 1, order_date: '2026-09-29 14:32', customer: 'MINISO国际', product_name: '鲨鱼毛绒公仔-60cm', quantity: 15000, note: '客户临时补单' },
  { id: 2, order_date: '2026-09-29 11:08', customer: 'TOP TOY', product_name: '鲨鱼毛绒公仔-60cm', quantity: 10000, note: '' },
  { id: 3, order_date: '2026-09-28 16:45', customer: '网易严选', product_name: '咸鱼按摩捶-海盐蓝', quantity: 5000, note: '' },
]

const RESPONSE = { logs: LOGS, pagination: { total: 1284, pages: 86 } }

function mountView() {
  mocks.queryData.value = RESPONSE
  return mount(ReportView, {
    global: {
      plugins: [[PrimeVue, { unstyled: true, pt: plushCutePT }]],
      stubs: {
        // 弹窗与确认框不全量挂载：本文件锁表格结构，弹窗链路各自有专项测试
        EditOrderModal: true,
        EditStockinModal: true,
        EditStockoutModal: true,
        EditReturnModal: true,
        ReportRecordPicker: true,
        UiConfirmDialog: true,
      },
    },
  })
}

/** ReportTable 单测挂载：不走 ReportView 的数据链路，直接锁操作列行为 */
function mountTable(logs: Record<string, unknown>[], canManage: boolean) {
  return mount(ReportTable, {
    props: {
      logs,
      columns: [
        { field: 'date', header: '下单时间', align: 'center', width: '16%' },
        { field: 'customer', header: '客户', align: 'center', width: '14%' },
        { field: 'product_name', header: '产品名称', align: 'left', width: '28%' },
        { field: 'quantity', header: '数量', align: 'center', width: '16%', sortable: true },
        { field: 'note', header: '备注', align: 'left', width: '17%' },
        { field: 'actions', header: '操作', align: 'left', width: '9%' },
      ],
      isLoading: false,
      isFetching: false,
      searched: true,
      perPage: 15,
      pagination: { total: logs.length, pages: 1 },
      currentCfg: {
        label: '订单流水', endpoint: '/reports/order-logs', dateKey: 'order_date',
        countKey: 'order_count', dateLabel: '下单时间', countLabel: '数量', noteKey: 'note',
      },
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
      searched: true,
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

    await w.find('input[aria-label="产品名称或 SKU"]').setValue('鲨鱼')

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

  it('tab 组、筛选、导出在同一行（同一工具条容器内）', () => {
    const w = mountView()

    expect(w.find('.rp-toolbar .rp-tab-group').exists()).toBe(true)
    expect(w.find('.rp-toolbar .rp-filter-bar').exists()).toBe(true)
    expect(w.find('.rp-toolbar [aria-label="导出"]').exists()).toBe(true)
  })

  it('不再有原来那个空着的卡片头（tab 原先独占一行）', () => {
    expect(mountView().find('.page-card-header').exists()).toBe(false)
  })
})

describe('ReportView —— 表格与数字格式', () => {
  it('订单流水六列按比例分配宽度（末列 9% 是操作列）', () => {
    const headers = mountView().findAll('th')
    const styles = headers.map((th) => th.attributes('style') ?? '')

    expect(styles[0]).toContain('16%')
    expect(styles[1]).toContain('14%')
    expect(styles[2]).toContain('28%')
    expect(styles[3]).toContain('16%')
    expect(styles[4]).toContain('17%')
    expect(styles[5]).toContain('9%')
  })

  it('数量走千分位并加粗', () => {
    const cells = mountView().findAll('tbody tr')[0]!.findAll('td')

    expect(cells[3]?.text()).toContain('15,000')
    expect(cells[3]?.find('.rp-qty').exists()).toBe(true)
  })

  it('空值留白，不显示「-」占位符', () => {
    const cells = mountView().findAll('tbody tr')[1]!.findAll('td')

    expect(cells[4]?.text()).toBe('')
  })

  it('数量列可排序（当前页客户端重排）', async () => {
    const w = mountView()

    await emitSort(w, 'quantity', 1)
    expect(w.findAll('tbody tr')[0]?.text()).toContain('5,000')

    await emitSort(w, 'quantity', -1)
    expect(w.findAll('tbody tr')[0]?.text()).toContain('15,000')
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
    // 有权限（2026-10-07）：五个维度都在末列追加 9% 操作列，备注列 26%→17%
    for (const tab of ALL) {
      const cols = useReportConfig(ref(tab), ref(true)).reportColumns.value
      expect(cols.at(-1)).toEqual({ field: 'actions', header: '操作', align: 'center', width: '9%' })
      expect(cols[cols.length - 2]!.width).toBe('17%')
    }
    // 无权限：整列不渲染（连表头一起），备注列收回 26%，不留空壳
    for (const tab of ALL) {
      const cols = useReportConfig(ref(tab), ref(false)).reportColumns.value
      expect(cols.some((c) => c.field === 'actions')).toBe(false)
      expect(cols[cols.length - 1]!.width).toBe('26%')
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
