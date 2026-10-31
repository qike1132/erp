/**
 * 报表页行内操作（2026-10-13 改「直连单条记录」）—— useReportRowActions 行为测试。
 *
 * 覆盖：各维度权限码映射、订单 tab 单 SKU 编辑/删除直连 /orders/items、
 * 出货/抵扣/退货按 record_id 直连各自单条接口、权限兜底拒绝。
 * （旧「聚合行还原 + picker」流程已随报表行改「一行一记录」整体移除。）
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
  updateItem: vi.fn(async () => ({})),
  deleteItem: vi.fn(async () => ({ message: '明细删除成功' })),
  editStockin: vi.fn(async () => ({})),
  deleteStockin: vi.fn(async () => ({})),
  editStockout: vi.fn(async () => ({})),
  deleteStockout: vi.fn(async () => ({})),
  returnUpdate: vi.fn(async () => ({ message: '退货修改成功' })),
  returnRemove: vi.fn(async () => ({})),
  hasPermission: vi.fn((_c: string) => true),
  hasAnyPermission: vi.fn((_c: string[]) => true),
  showToast: vi.fn(),
  confirm: vi.fn(async () => true),
  invalidateQueries: vi.fn(),
}))

vi.mock('@/api', () => ({
  orderApi: { updateItem: mocks.updateItem, deleteItem: mocks.deleteItem },
  stockApi: {
    editStockin: mocks.editStockin,
    deleteStockin: mocks.deleteStockin,
    editStockout: mocks.editStockout,
    deleteStockout: mocks.deleteStockout,
  },
  stockReturnApi: { update: mocks.returnUpdate, remove: mocks.returnRemove },
}))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ hasPermission: mocks.hasPermission, hasAnyPermission: mocks.hasAnyPermission }),
}))
vi.mock('@/composables/useToast', () => ({ showToast: mocks.showToast }))
vi.mock('@/composables/useConfirmDialog', () => ({
  useConfirmDialog: () => ({
    confirm: mocks.confirm,
    open: { value: false }, text: { value: '' }, sub: { value: '' }, type: { value: 'danger' },
    onConfirm: vi.fn(), onCancel: vi.fn(),
  }),
}))
vi.mock('@tanstack/vue-query', () => ({
  useQueryClient: () => ({ invalidateQueries: mocks.invalidateQueries }),
}))

import { useReportRowActions, TAB_ROW_PERMISSIONS } from '@/views/report/composables/useReportRowActions'

function makeActions() {
  let api: ReturnType<typeof useReportRowActions> | null = null
  const Comp = defineComponent({
    setup() {
      api = useReportRowActions()
      return () => h('div')
    },
  })
  mount(Comp)
  return api!
}

/** 报表行（后端 ReportLogItem）——订单 tab 一行一 SKU */
const ORDER_ROW = {
  order_id: 7, item_id: 12, order_no: 'SO-1', order_date: '2026-10-13 09:12',
  customer: 'MINISO国际', product_name: '鲨鱼公仔', product_barcode: '690', quantity: 150,
  item_note: '加急', order_note: '整单备注', item_count: 2, order_total_qty: 300,
}
const STOCKOUT_ROW = {
  record_id: 21, record_no: 'SO-20261001-1', stockout_date: '2026-10-01 10:00',
  customer: 'MINISO国际', product_name: '鲨鱼公仔', product_barcode: '690', quantity: 12, note: '急单',
}
// 抵扣行真实形状（get_deduction_logs）：quantity 是**净量**、另有 gross_quantity/stockout_date/note
// （回归评审 I-1：若照搬 stockout 行键，编辑会把毛量改成净量）
const DEDUCTION_ROW = {
  record_id: 22, record_no: 'SO-D1', deduction_time: '2026-10-01 10:00', stockout_date: '2026-10-01 10:00',
  customer: 'MINISO国际', product_name: '鲨鱼公仔', product_barcode: '690',
  quantity: 80, gross_quantity: 100, note: '出货备注', order_no: 'SO-9', order_note: '订单备注',
}
// 退货行真实形状：reason 与 note 分开下发（回归评审 I-3：reason 不能丢）
const RETURN_ROW = {
  record_id: 31, record_no: 'SR-20261001-1', return_date: '2026-10-01 11:00',
  customer: 'MINISO国际', product_name: '鲨鱼公仔', product_barcode: '690',
  quantity: 4, reason: '破损', note: '客户反馈', note_display: '破损；客户反馈',
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.hasPermission.mockReturnValue(true)
  mocks.hasAnyPermission.mockReturnValue(true)
  mocks.confirm.mockResolvedValue(true)
})

describe('TAB_ROW_PERMISSIONS', () => {
  it('每个 TAB 一对独立码（迁移 091 起备货也独立）；每项镜像后端 require_any 的 manage 兜底', () => {
    expect(TAB_ROW_PERMISSIONS.order).toEqual({ edit: ['order_edit', 'order_manage'], delete: ['order_delete', 'order_manage'] })
    expect(TAB_ROW_PERMISSIONS.stockin).toEqual({ edit: ['stockin_edit', 'order_manage', 'stockin_manage'], delete: ['stockin_delete', 'order_manage', 'stockin_manage'] })
    expect(TAB_ROW_PERMISSIONS.stockout).toEqual({ edit: ['stockout_edit', 'stockout_manage'], delete: ['stockout_delete', 'stockout_manage'] })
    expect(TAB_ROW_PERMISSIONS.deduction).toEqual({ edit: ['deduction_edit', 'stockout_manage'], delete: ['deduction_delete', 'stockout_manage'] })
    expect(TAB_ROW_PERMISSIONS.return).toEqual({ edit: ['return_edit', 'stock_return_manage'], delete: ['return_delete', 'stock_return_manage'] })
  })
})

describe('订单流水：单 SKU 直连', () => {
  it('编辑：打开明细弹窗，表单取该行的 item_id/数量/备注', async () => {
    const api = makeActions()
    await api.onRowAction('order', 'edit', ORDER_ROW)

    expect(api.orderItemEditVisible.value).toBe(true)
    expect(api.orderItemEditForm.value).toMatchObject({ itemId: 12, productName: '鲨鱼公仔', quantity: 150, note: '加急' })
  })

  it('删除：直接调 deleteItem(item_id)，不再走还原/picker', async () => {
    const api = makeActions()
    await api.onRowAction('order', 'delete', ORDER_ROW)

    expect(mocks.deleteItem).toHaveBeenCalledWith(12)
    expect(mocks.invalidateQueries).toHaveBeenCalled()
  })

  it('保存：调 updateItem(item_id, {quantity, note})', async () => {
    const api = makeActions()
    await api.onRowAction('order', 'edit', ORDER_ROW)
    api.orderItemEditForm.value = { ...api.orderItemEditForm.value!, quantity: 200, note: '改' }
    await api.saveOrderItemEdit()

    expect(mocks.updateItem).toHaveBeenCalledWith(12, { quantity: 200, note: '改' })
    expect(api.orderItemEditVisible.value).toBe(false)
  })

  it('写入成功后失效订单派生查询（含 inventory）——2026-10-31 /stock 延迟修复', async () => {
    // 回归：refreshAfterWrite 曾只失效 ['report-data']；inventory 被持久化到
    // sessionStorage 且 staleTime 30s，改完在别处打开 /stock 会命中旧快照
    // 不发请求，约 20~30s 后才更新。必须走 invalidateOrderDerivedQueries 整体失效。
    const api = makeActions()
    await api.onRowAction('order', 'edit', ORDER_ROW)
    api.orderItemEditForm.value = { ...api.orderItemEditForm.value!, quantity: 200, note: '改' }
    await api.saveOrderItemEdit()

    expect(mocks.updateItem).toHaveBeenCalled()
    const keys = mocks.invalidateQueries.mock.calls.map((c: unknown[]) => (c[0] as { queryKey: string[] }).queryKey)
    const prefixes = keys.map((k) => k[0])
    expect(prefixes).toContain('inventory')
    expect(prefixes).toContain('report-data')
  })

  it('无 item_id（历史订单）时拒绝，不调接口', async () => {
    const api = makeActions()
    await api.onRowAction('order', 'delete', { ...ORDER_ROW, item_id: 0 })

    expect(mocks.deleteItem).not.toHaveBeenCalled()
    expect(mocks.showToast).toHaveBeenCalled()
  })
})

describe('出货 / 备货抵扣流水：按 record_id 直连', () => {
  it('出货删除：调 deleteStockout(record_id)', async () => {
    const api = makeActions()
    await api.onRowAction('stockout', 'delete', STOCKOUT_ROW)

    expect(mocks.deleteStockout).toHaveBeenCalledWith(21)
  })

  it('抵扣删除：调 deleteStockout(record_id)，编辑弹窗标 isDeduction', async () => {
    const api = makeActions()
    await api.onRowAction('deduction', 'edit', DEDUCTION_ROW)

    expect(api.stockoutEditVisible.value).toBe(true)
    expect(api.stockoutEditIsDeduction.value).toBe(true)
    // 回归 I-1：数量必须取**毛量**（gross_quantity=100），不能取净量 80
    expect(api.stockoutEditForm.value).toMatchObject({ id: 22, stockoutNo: 'SO-D1', quantity: 100, note: '出货备注' })
  })

  it('抵扣编辑保存：回写毛量而非净量（不把出货量改错）', async () => {
    const api = makeActions()
    await api.onRowAction('deduction', 'edit', DEDUCTION_ROW)
    await api.saveStockoutEdit()

    expect(mocks.editStockout).toHaveBeenCalledWith(22, expect.objectContaining({ quantity: 100 }))
  })

  it('出货编辑保存：客户随表单下发', async () => {
    const api = makeActions()
    await api.onRowAction('stockout', 'edit', STOCKOUT_ROW)
    await api.saveStockoutEdit()

    expect(mocks.editStockout).toHaveBeenCalledWith(21, expect.objectContaining({ quantity: 12, customer: 'MINISO国际' }))
  })
})

describe('退货流水：按 record_id 直连', () => {
  it('删除：调 stockReturnApi.remove(record_id)', async () => {
    const api = makeActions()
    await api.onRowAction('return', 'delete', RETURN_ROW)

    expect(mocks.returnRemove).toHaveBeenCalledWith(31)
  })

  it('编辑：打开弹窗并按 record_id 保存（reason 原值回写，不被清空）', async () => {
    const api = makeActions()
    await api.onRowAction('return', 'edit', RETURN_ROW)
    expect(api.returnEditVisible.value).toBe(true)
    expect(api.returnEditForm.value).toMatchObject({ id: 31, reason: '破损', note: '客户反馈' })
    await api.saveReturnEdit()

    // 回归 I-3：reason 必须是 '破损'（旧映射硬编码 '' → 保存会清空原因）
    expect(mocks.returnUpdate).toHaveBeenCalledWith(31, expect.objectContaining({ quantity: 4, reason: '破损' }))
  })
})

describe('权限兜底', () => {
  it('无编辑权限：拒绝且不调接口', async () => {
    mocks.hasAnyPermission.mockReturnValue(false)
    const api = makeActions()
    await api.onRowAction('order', 'edit', ORDER_ROW)

    expect(api.orderItemEditVisible.value).toBe(false)
    expect(mocks.updateItem).not.toHaveBeenCalled()
    expect(mocks.showToast).toHaveBeenCalled()
  })

  it('无删除权限：拒绝且不调接口', async () => {
    mocks.hasAnyPermission.mockReturnValue(false)
    const api = makeActions()
    await api.onRowAction('order', 'delete', ORDER_ROW)

    expect(mocks.deleteItem).not.toHaveBeenCalled()
  })
})
