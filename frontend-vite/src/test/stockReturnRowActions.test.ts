/**
 * /stock-return 行内「修改」「删除」——与 /report 退货流水同逻辑（2026-10-08）。
 *
 * 覆盖：行 → 编辑表单映射、保存走 PUT /stock-returns/{id}、数量非法不提交、
 * 失败保持弹窗打开（成功才关）、删除走软取消 DELETE 并带二次确认。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  shipmentOptions: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  remove: vi.fn(),
  hasPermission: vi.fn((_c: string) => true),
  showToast: vi.fn(),
  confirm: vi.fn(async () => true),
  invalidateQueries: vi.fn(),
}))

vi.mock('@/api', () => ({
  stockReturnApi: {
    list: mocks.list,
    shipmentOptions: mocks.shipmentOptions,
    create: mocks.create,
    update: mocks.update,
    remove: mocks.remove,
  },
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: mocks.hasPermission }) }))
vi.mock('@/composables/useToast', () => ({ showToast: mocks.showToast }))
vi.mock('@/composables/useConfirmDialog', () => ({
  useConfirmDialog: () => ({
    confirm: mocks.confirm,
    open: { value: false }, text: { value: '' }, sub: { value: '' }, type: { value: 'danger' },
    onConfirm: vi.fn(), onCancel: vi.fn(),
  }),
}))
vi.mock('@tanstack/vue-query', () => ({
  useQuery: () => ({ data: { value: undefined }, isLoading: { value: false } }),
  useQueryClient: () => ({ invalidateQueries: mocks.invalidateQueries }),
  keepPreviousData: undefined,
}))

import { useStockReturn } from '@/views/stock-return/composables/useStockReturn'
import type { StockReturnRecord } from '@/api/stockReturn'

function makeApi() {
  let api: ReturnType<typeof useStockReturn> | null = null
  const Comp = defineComponent({
    setup() {
      api = useStockReturn()
      return () => h('div')
    },
  })
  mount(Comp)
  return api!
}

const ROW: StockReturnRecord = {
  id: 31, return_no: 'SR-20261008-0001', return_date: '2026-10-08',
  product: { id: 3, name: '鲨鱼公仔' }, quantity: 4, customer: 'MINISO国际',
  stockout_id: 21, stockout_no: 'SO-1', reason: '破损', note: '备注', status: 'active',
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.hasPermission.mockReturnValue(true)
  mocks.confirm.mockResolvedValue(true)
})

describe('退货修改', () => {
  it('打开弹窗：按行填充表单（产品名取 product.name，日期截到天）', () => {
    const api = makeApi()
    api.openReturnEdit(ROW)
    expect(api.returnEditVisible.value).toBe(true)
    expect(api.returnEditForm.value).toEqual({
      id: 31,
      returnNo: 'SR-20261008-0001',
      productName: '鲨鱼公仔',
      quantity: 4,
      customer: 'MINISO国际',
      date: '2026-10-08',
      reason: '破损',
      note: '备注',
    })
  })

  it('保存：调 PUT /stock-returns/{id}，成功后关弹窗', async () => {
    mocks.update.mockResolvedValue({ success: true, message: '退货修改成功' })
    const api = makeApi()
    api.openReturnEdit(ROW)

    await api.saveReturnEdit()

    expect(mocks.update).toHaveBeenCalledWith(31, {
      quantity: 4, return_date: '2026-10-08', reason: '破损', note: '备注',
    })
    expect(api.returnEditVisible.value).toBe(false)
  })

  it('数量非法（<1）：不提交，弹窗保持打开', async () => {
    const api = makeApi()
    api.openReturnEdit(ROW)
    api.returnEditForm.value!.quantity = 0

    await api.saveReturnEdit()

    expect(mocks.update).not.toHaveBeenCalled()
    expect(api.returnEditVisible.value).toBe(true)
  })

  it('保存失败：不关弹窗（run 返回 undefined）', async () => {
    mocks.update.mockRejectedValue(new Error('boom'))
    const api = makeApi()
    api.openReturnEdit(ROW)

    await api.saveReturnEdit()

    expect(api.returnEditVisible.value).toBe(true)
  })
})

describe('退货删除', () => {
  it('二次确认后调软取消接口', async () => {
    mocks.remove.mockResolvedValue({ success: true, message: '退货取消成功' })
    const api = makeApi()

    await api.handleDelete(ROW)

    expect(mocks.confirm).toHaveBeenCalled()
    expect(mocks.remove).toHaveBeenCalledWith(31)
  })

  it('确认框取消：不调用接口', async () => {
    mocks.confirm.mockResolvedValue(false)
    const api = makeApi()

    await api.handleDelete(ROW)

    expect(mocks.remove).not.toHaveBeenCalled()
  })
})
