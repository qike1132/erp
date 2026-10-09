/**
 * 报表页行内操作（出货 / 备货抵扣 / 退货）—— useReportRowActions 行为测试（2026-10-07）。
 *
 * 覆盖：各维度权限码映射、聚合行还原（出货按 stockout_no、抵扣按 order_no、退货按 return_no）、
 * 单条直开对应编辑弹窗、多条弹 picker、权限兜底拒绝、保存/删除的写路径与抵扣行客户不下发。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
  orderRecords: vi.fn(),
  stockoutRecords: vi.fn(),
  editStockout: vi.fn(),
  deleteStockout: vi.fn(),
  returnRecords: vi.fn(),
  returnUpdate: vi.fn(),
  returnRemove: vi.fn(),
  hasPermission: vi.fn((_c: string) => true),
  hasAnyPermission: vi.fn((_c: string[]) => true),
  showToast: vi.fn(),
  confirm: vi.fn(async () => true),
  invalidateQueries: vi.fn(),
}))

vi.mock('@/api', () => ({
  orderApi: { records: mocks.orderRecords, detail: vi.fn(), update: vi.fn(), updateDeduct: vi.fn(), delete: vi.fn() },
  stockApi: {
    stockoutRecords: mocks.stockoutRecords,
    editStockout: mocks.editStockout,
    deleteStockout: mocks.deleteStockout,
    deleteStockin: vi.fn(),
  },
  stockReturnApi: {
    records: mocks.returnRecords,
    update: mocks.returnUpdate,
    remove: mocks.returnRemove,
  },
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

const STOCKOUT_REC = {
  id: 21, stockout_no: 'SO-20261001-1', stockout_date: '2026-10-01', customer: 'MINISO国际',
  product_id: 3, product_name: '鲨鱼公仔', barcode: '690', quantity: 12, returned_quantity: 2,
  note: '急单', stockin_id: null, order_id: 7,
}
const DEDUCTION_REC = { ...STOCKOUT_REC, id: 22, stockout_no: 'SO-D1', stockin_id: 5 }
const RETURN_REC = {
  id: 31, return_no: 'SR-20261001-1', return_date: '2026-10-01', customer: 'MINISO国际',
  product_id: 3, product_name: '鲨鱼公仔', quantity: 4, stockout_id: 21, stockout_no: 'SO-1',
  reason: '破损', note: '备注',
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.hasPermission.mockReturnValue(true)
  mocks.hasAnyPermission.mockReturnValue(true)
  mocks.confirm.mockResolvedValue(true)
})

describe('TAB_ROW_PERMISSIONS', () => {
  it('订单/备货用 order_*，出货/抵扣/退货各自独立码；每项镜像后端 require_any 的 manage 兜底', () => {
    expect(TAB_ROW_PERMISSIONS.order).toEqual({ edit: ['order_edit', 'order_manage'], delete: ['order_delete', 'order_manage'] })
    expect(TAB_ROW_PERMISSIONS.stockin).toEqual({ edit: ['order_edit', 'order_manage', 'stockin_manage'], delete: ['order_delete', 'order_manage', 'stockin_manage'] })
    expect(TAB_ROW_PERMISSIONS.stockout).toEqual({ edit: ['stockout_edit', 'stockout_manage'], delete: ['stockout_delete', 'stockout_manage'] })
    expect(TAB_ROW_PERMISSIONS.deduction).toEqual({ edit: ['deduction_edit', 'stockout_manage'], delete: ['deduction_delete', 'stockout_manage'] })
    expect(TAB_ROW_PERMISSIONS.return).toEqual({ edit: ['return_edit', 'stock_return_manage'], delete: ['return_delete', 'stock_return_manage'] })
  })
})

describe('订单/备货流水行内操作', () => {
  it('备货行：order_nos 为空串（后端默认值）时按 stockin_nos 还原', async () => {
    mocks.orderRecords.mockResolvedValue({ data: [
      { id: 5, record_type: 'stockin', order_no: 'BH-20261001-1', customer: 'MINISO国际', order_date: '2026-10-01' },
    ] })
    const api = makeActions()

    // 回归 2026-10-08：后端 ReportLogItem 的 order_nos 默认值是 ''（非 null），
    // 旧写法 `row.order_nos ?? row.stockin_nos` 会取到空串 → 单号为空 →
    // 弹「未能找到该组对应的明细记录」，备货流水行内操作恒失败。
    await api.onRowAction('stockin', 'delete', {
      order_nos: '', stockin_nos: 'BH-20261001-1', stockin_date: '2026-10-01', customer: 'MINISO国际',
    })

    expect(mocks.orderRecords).toHaveBeenCalledWith(expect.objectContaining({
      record_type: 'stockin', start_date: '2026-10-01', end_date: '2026-10-01',
    }))
    expect(mocks.showToast).not.toHaveBeenCalledWith('未能找到该组对应的明细记录', 'error')
  })

  it('订单行：按 order_nos 还原', async () => {
    mocks.orderRecords.mockResolvedValue({ data: [
      { id: 7, record_type: 'order', order_no: 'PO-1', customer: 'MINISO国际', order_date: '2026-10-01' },
    ] })
    const api = makeActions()

    await api.onRowAction('order', 'delete', {
      order_nos: 'PO-1', order_date: '2026-10-01', customer: 'MINISO国际',
    })

    expect(mocks.orderRecords).toHaveBeenCalledWith(expect.objectContaining({
      record_type: 'order', start_date: '2026-10-01', end_date: '2026-10-01',
    }))
  })
})

describe('出货流水行内操作', () => {
  it('单条：按 stockout_no 还原并打开出货编辑弹窗', async () => {
    mocks.stockoutRecords.mockResolvedValue({ data: [STOCKOUT_REC] })
    const api = makeActions()

    await api.onRowAction('stockout', 'edit', { stockout_nos: 'SO-20261001-1', customer: 'MINISO国际', product_name: '鲨鱼公仔' })

    expect(mocks.stockoutRecords).toHaveBeenCalledWith('stockout', 'SO-20261001-1', '鲨鱼公仔')
    expect(api.stockoutEditVisible.value).toBe(true)
    expect(api.stockoutEditIsDeduction.value).toBe(false)
    expect(api.stockoutEditForm.value?.stockoutNo).toBe('SO-20261001-1')
    expect(api.stockoutEditForm.value?.quantity).toBe(12)
  })

  it('抵扣：按 order_no 还原（带产品名收窄），标记为抵扣行', async () => {
    mocks.stockoutRecords.mockResolvedValue({ data: [DEDUCTION_REC] })
    const api = makeActions()

    await api.onRowAction('deduction', 'edit', { order_nos: 'PO-1', customer: 'MINISO国际', product_name: '鲨鱼公仔' })

    // 产品名一并下发：同一订单对多产品抵扣时避免还原出他产品的行
    expect(mocks.stockoutRecords).toHaveBeenCalledWith('deduction', 'PO-1', '鲨鱼公仔')
    expect(api.stockoutEditIsDeduction.value).toBe(true)
    expect(api.stockoutEditVisible.value).toBe(true)
  })

  it('多条：打开选择弹窗，不直接编辑', async () => {
    mocks.stockoutRecords.mockResolvedValue({ data: [STOCKOUT_REC, { ...STOCKOUT_REC, id: 99 }] })
    const api = makeActions()

    await api.onRowAction('stockout', 'edit', { stockout_nos: 'SO-1,SO-2' })

    expect(api.pickerOpen.value).toBe(true)
    expect(api.stockoutEditVisible.value).toBe(false)
    expect(api.pickerRecords.value).toHaveLength(2)
    expect(api.pickerKeys.value.noKey).toBe('stockout_no')
  })

  it('无权限：toast 拒绝，不发起还原请求', async () => {
    mocks.hasAnyPermission.mockReturnValue(false)
    const api = makeActions()

    await api.onRowAction('stockout', 'edit', { stockout_nos: 'SO-1' })

    expect(mocks.showToast).toHaveBeenCalled()
    expect(mocks.stockoutRecords).not.toHaveBeenCalled()
    expect(api.stockoutEditVisible.value).toBe(false)
  })

  it('保存出货编辑：调 editStockout 并失效报表缓存', async () => {
    mocks.editStockout.mockResolvedValue({ success: true })
    const api = makeActions()
    api.stockoutEditForm.value = {
      id: 21, stockoutNo: 'SO-1', productName: '鲨鱼公仔', quantity: 15,
      customer: 'MINISO国际', date: '2026-10-02', note: '改',
    }
    api.stockoutEditIsDeduction.value = false

    await api.saveStockoutEdit()

    expect(mocks.editStockout).toHaveBeenCalledWith(21, expect.objectContaining({ quantity: 15, customer: 'MINISO国际', stockout_date: '2026-10-02' }))
    expect(mocks.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['report-data'] })
    expect(api.stockoutEditVisible.value).toBe(false)
  })

  it('保存抵扣编辑：不下发 customer（由订单/备货带出）', async () => {
    mocks.editStockout.mockResolvedValue({ success: true })
    const api = makeActions()
    api.stockoutEditForm.value = {
      id: 22, stockoutNo: 'SO-D1', productName: '鲨鱼公仔', quantity: 6,
      customer: '被忽略的客户', date: '2026-10-02', note: '',
    }
    api.stockoutEditIsDeduction.value = true

    await api.saveStockoutEdit()

    const payload = mocks.editStockout.mock.calls[0]![1] as Record<string, unknown>
    expect(payload.quantity).toBe(6)
    expect('customer' in payload).toBe(false)
  })

  it('删除：确认后调 deleteStockout', async () => {
    mocks.stockoutRecords.mockResolvedValue({ data: [STOCKOUT_REC] })
    mocks.deleteStockout.mockResolvedValue({ success: true })
    const api = makeActions()

    await api.onRowAction('stockout', 'delete', { stockout_nos: 'SO-1' })
    // 单条直开会直接走删除确认
    expect(mocks.confirm).toHaveBeenCalled()
    expect(mocks.deleteStockout).toHaveBeenCalledWith(21)
  })
})

describe('退货流水行内操作', () => {
  it('单条：按 return_no 还原并打开退货编辑弹窗', async () => {
    mocks.returnRecords.mockResolvedValue({ data: [RETURN_REC] })
    const api = makeActions()

    await api.onRowAction('return', 'edit', { return_nos: 'SR-20261001-1', customer: 'MINISO国际' })

    expect(mocks.returnRecords).toHaveBeenCalledWith('SR-20261001-1')
    expect(api.returnEditVisible.value).toBe(true)
    expect(api.returnEditForm.value?.returnNo).toBe('SR-20261001-1')
    expect(api.returnEditForm.value?.reason).toBe('破损')
  })

  it('保存退货编辑：调 update', async () => {
    mocks.returnUpdate.mockResolvedValue({ success: true, message: '退货修改成功！单号 SR-NEW' })
    const api = makeActions()
    api.returnEditForm.value = {
      id: 31, returnNo: 'SR-1', productName: '鲨鱼公仔', quantity: 6,
      customer: 'MINISO国际', date: '2026-10-03', reason: '新原因', note: '新备注',
    }

    await api.saveReturnEdit()

    expect(mocks.returnUpdate).toHaveBeenCalledWith(31, expect.objectContaining({ quantity: 6, return_date: '2026-10-03', reason: '新原因', note: '新备注' }))
    expect(api.returnEditVisible.value).toBe(false)
  })

  it('取消退货：确认后调 remove', async () => {
    mocks.returnRecords.mockResolvedValue({ data: [RETURN_REC] })
    mocks.returnRemove.mockResolvedValue({ success: true, message: 'ok' })
    const api = makeActions()

    await api.onRowAction('return', 'delete', { return_nos: 'SR-1' })

    expect(mocks.confirm).toHaveBeenCalled()
    expect(mocks.returnRemove).toHaveBeenCalledWith(31)
  })
})
