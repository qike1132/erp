/**
 * Task 9（BOM 实时同步）：采购明细版本 items_version 的前端乐观锁契约。
 *
 * 后端（Task 6）已就绪：
 * - `POST /purchase-center/orders/factory-summary` 响应顶层带 `items_versions: {po_id: int}`；
 * - `POST .../factory-summary/save` 请求可带 `items_versions`，版本过期返回 409
 *   （body code `ITEMS_VERSION_CONFLICT`）；
 * - `PUT /purchase-center/orders/{id}` 请求可带 `items_version`，过期同样 409。
 *
 * 前端契约：
 *  C1 openSummary 记录版本快照；
 *  C2 「保存修改」把版本原样带回后端；
 *  C3 409 → warning 提示「BOM 已更新…」+ 重新拉汇总（拿到新明细/新版本）+ 仍然 reject
 *     （上层不得显示「修改已保存」）；
 *  C4 订单详情保存单价携带订单的 items_version；
 *  C5 单价保存 409 → warning 提示 + 重新拉单（emit saved），不显示「单价已保存」。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

vi.mock('@/api', () => ({
  purchaseApi: {
    factorySummary: vi.fn(),
    supplierSummary: vi.fn(),
    saveFactoryEdits: vi.fn(),
    supplierSummaryExport: vi.fn(),
    updateItemPrices: vi.fn(),
  },
}))

vi.mock('@/composables/useToast', () => ({
  showToast: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))

vi.mock('@/composables/useExport', async () => {
  const { ref: r } = await import('vue')
  return { useExport: () => ({ exporting: r(false), runExport: vi.fn() }) }
})

import { useSummaryModal } from '@/views/purchase/composables/useSummaryModal'
import { usePurchaseActions } from '@/views/purchase/composables/usePurchaseActions'
import type { FactorySummaryData } from '@/views/purchase/composables/useSummaryModal'
import OrderDetailModal from '@/views/purchase/components/OrderDetailModal.vue'
import { purchaseApi } from '@/api'
import { showToast, toast } from '@/composables/useToast'
import type { PurchaseOrder } from '@/types'

/** 一张待产采购单：落库明细 100（item 11），订单级率 30‰，明细版本 3。 */
const FACTORY: FactorySummaryData = {
  success: true,
  order_count: 1,
  spare_rate: 30,
  items_versions: { '7': 3 },
  groups: [
    {
      customer_name: '网易',
      product_name: '《蛋仔派对》缤果乐园系列',
      product_quantity: 100,
      suppliers: [
        {
          supplier_name: '三虎',
          fabrics: [
            {
              fabric_name: '宝乐绒', specification: '01#', unit: '码',
              quantity: 100, item_ids: [11], loss_rate: 0,
            },
          ],
        },
      ],
      skus: [
        {
          product_name: '香蕉',
          order_qty: 100,
          materials: [
            {
              supplier_name: '三虎', material_name: '宝乐绒', specification: '01#',
              unit: '码', quantity: 100, part_name: '',
            },
          ],
        },
      ],
    },
  ],
}

const SUPPLIER = {
  success: true,
  materials: [
    {
      material_name: '宝乐绒', specification: '01#', unit: '码',
      total_quantity: 100, supplier_name: '三虎',
    },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(purchaseApi.factorySummary).mockResolvedValue(FACTORY as never)
  vi.mocked(purchaseApi.supplierSummary).mockResolvedValue(SUPPLIER as never)
  vi.mocked(purchaseApi.saveFactoryEdits).mockResolvedValue({ success: true } as never)
  vi.mocked(purchaseApi.updateItemPrices).mockResolvedValue({ success: true } as never)
})

describe('汇总保存：items_versions 乐观锁', () => {
  it('openSummary 记录版本快照；保存修改时原样带回（第 4 参）', async () => {
    const m = useSummaryModal()
    await m.openSummary([7])
    expect(m.itemsVersions).toEqual({ '7': 3 })

    m.toggleEditMode(true)
    // 率=0（逐行 loss_rate: 0）→ 输入框值即落库真值，diff 得 quantity=1100
    m.updateFactoryQty(0, 0, 0, 1100)
    await m.saveFactoryEdits()

    expect(purchaseApi.saveFactoryEdits).toHaveBeenCalledTimes(1)
    expect(purchaseApi.saveFactoryEdits).toHaveBeenCalledWith(
      [{ item_ids: [11], quantity: 1100 }],
      undefined,
      [7],
      { '7': 3 },
    )
    // 旧后端/响应缺 items_versions：本地快照保持原值（不因缺字段被清空）
    expect(m.itemsVersions).toEqual({ '7': 3 })
    // 正常保存不得出现 409 提示
    expect(toast.warning).not.toHaveBeenCalled()
  })

  it('保存成功响应带 items_versions：本地快照前移，后续保存不再带过期版本', async () => {
    // 用户编辑数量也会递增 items_version（spec 同步算法-7）：响应回传新版本
    vi.mocked(purchaseApi.saveFactoryEdits).mockResolvedValueOnce(
      { success: true, items_versions: { '7': 4 } } as never,
    )

    const m = useSummaryModal()
    await m.openSummary([7])
    expect(m.itemsVersions).toEqual({ '7': 3 })
    m.toggleEditMode(true)
    m.updateFactoryQty(0, 0, 0, 1100)
    await m.saveFactoryEdits()

    expect(m.itemsVersions).toEqual({ '7': 4 })
  })

  it('损耗率自动落库响应带 items_versions：版本快照同步前移', async () => {
    // spare_rate 覆盖写同样递增 items_version；不回收新版本会让之后的
    // 「保存修改」带过期版本被 409。
    vi.mocked(purchaseApi.saveFactoryEdits).mockResolvedValueOnce(
      { success: true, items_versions: { '7': 5 } } as never,
    )

    const m = useSummaryModal()
    await m.openSummary([7])
    await m.applyLossRateAndSave(50)

    expect(purchaseApi.saveFactoryEdits).toHaveBeenCalledWith([], 50, [7])
    expect(m.itemsVersions).toEqual({ '7': 5 })
  })

  it('409 冲突：warning 提示「BOM 已更新」+ 重新拉汇总（版本前移）+ 仍 reject', async () => {
    vi.mocked(purchaseApi.saveFactoryEdits).mockRejectedValueOnce({ response: { status: 409 } })
    // 刷新后后端已把版本递增到 4：openSummary 必须记录新版本
    vi.mocked(purchaseApi.factorySummary)
      .mockResolvedValueOnce(FACTORY as never)
      .mockResolvedValueOnce({ ...FACTORY, items_versions: { '7': 4 } } as never)

    const m = useSummaryModal()
    await m.openSummary([7])
    m.toggleEditMode(true)
    m.updateFactoryQty(0, 0, 0, 1100)

    await expect(m.saveFactoryEdits()).rejects.toBeTruthy()

    expect(toast.warning).toHaveBeenCalledWith(expect.stringContaining('BOM 已更新'))
    // 重新拉取工厂 + 供应商汇总（openSummary 共两次）
    expect(purchaseApi.factorySummary).toHaveBeenCalledTimes(2)
    expect(purchaseApi.supplierSummary).toHaveBeenCalledTimes(2)
    expect(m.itemsVersions).toEqual({ '7': 4 })
    // 刷新回到展示态：用户需基于最新明细重新进入编辑
    expect(m.editMode).toBe(false)
  })

  it('关闭后 409 迟到：不重新打开弹窗、不再拉汇总', async () => {
    let rejectSave!: (reason: unknown) => void
    vi.mocked(purchaseApi.saveFactoryEdits).mockImplementationOnce(
      () => new Promise<never>((_resolve, reject) => { rejectSave = reject }),
    )

    const m = useSummaryModal()
    await m.openSummary([7])
    m.toggleEditMode(true)
    m.updateFactoryQty(0, 0, 0, 1100)

    const saving = m.saveFactoryEdits()
    // 请求在途期间用户关闭了弹窗（orderIds 已清空）
    m.close()
    rejectSave({ response: { status: 409 } })

    await expect(saving).rejects.toBeTruthy()
    // 提示仍会弹出（告知刚才的保存没生效），但不得刷新——
    // 否则会用空 orderIds 重新打开一个空弹窗。
    expect(toast.warning).toHaveBeenCalledWith(expect.stringContaining('BOM 已更新'))
    expect(purchaseApi.factorySummary).toHaveBeenCalledTimes(1)
    expect(purchaseApi.supplierSummary).toHaveBeenCalledTimes(1)
    expect(m.open).toBe(false)
    expect(m.orderIds).toEqual([])
  })

  it('上层 handler 收到 409 时不再弹通用错误（warning 已由汇总弹窗弹出）', async () => {
    vi.mocked(purchaseApi.saveFactoryEdits).mockRejectedValueOnce({ response: { status: 409 } })
    vi.mocked(purchaseApi.factorySummary)
      .mockResolvedValueOnce(FACTORY as never)
      .mockResolvedValueOnce({ ...FACTORY, items_versions: { '7': 4 } } as never)

    const m = useSummaryModal()
    await m.openSummary([7])
    const actions = usePurchaseActions({
      purchaseOrders: {} as never,
      completed: {} as never,
      summary: m,
      confirm: {} as never,
      queryClient: {} as never,
    })
    m.toggleEditMode(true)
    m.updateFactoryQty(0, 0, 0, 1100)
    await actions.handleSaveFactoryEdits()

    // warning 来自 composable；handler 不得再弹第二条（英文 axios 错误 /「保存失败」）
    expect(toast.warning).toHaveBeenCalledTimes(1)
    expect(showToast).not.toHaveBeenCalled()
    // 数据仍按 409 契约刷新过
    expect(purchaseApi.factorySummary).toHaveBeenCalledTimes(2)
    expect(m.itemsVersions).toEqual({ '7': 4 })
  })
})

describe('订单详情单价保存：items_version 乐观锁', () => {
  const stubs = {
    UiDialog: { template: '<div class="ui-dialog-stub"><slot name="footer" /><slot /></div>' },
  }

  function makeOrder(overrides: Partial<PurchaseOrder> = {}): PurchaseOrder {
    return {
      id: 100,
      order_no: 'CG-20261111-0001',
      status: 'pending',
      total_amount: 0,
      items_version: 5,
      items: [
        { id: 1, material_name: '面料A', quantity: 10, unit: '米', unit_price: 0 },
        { id: 2, material_name: '配件B', quantity: 4, unit: '个', unit_price: 5 },
      ],
      ...overrides,
    } as PurchaseOrder
  }

  function mountModal(order: PurchaseOrder) {
    return mount(OrderDetailModal, { props: { open: true, order }, global: { stubs } })
  }

  async function editFirstPriceAndSave(wrapper: ReturnType<typeof mountModal>) {
    await wrapper.findAll('input.odm-price-input')[0]!.setValue('3.5')
    await wrapper.get('button.odm-save').trigger('click')
    await flushPromises()
  }

  it('保存单价时携带订单的 items_version', async () => {
    const w = mountModal(makeOrder())
    await editFirstPriceAndSave(w)

    expect(purchaseApi.updateItemPrices).toHaveBeenCalledWith(
      100,
      [{ id: 1, unit_price: 3.5 }],
      5,
    )
    expect(showToast).toHaveBeenCalledWith('单价已保存', 'success')
  })

  it('保存单价响应带新版本：回写本地订单对象，下一次保存携带新版本', async () => {
    // 后端对用户改价也递增 items_version：响应 order.items_version 必须回写本地，
    // 否则同一详情页连续保存第二次会带过期版本被 409。
    vi.mocked(purchaseApi.updateItemPrices).mockResolvedValueOnce(
      { success: true, order: { items_version: 6 } } as never,
    )
    const order = makeOrder()
    const w = mountModal(order)
    await editFirstPriceAndSave(w)
    expect(order.items_version).toBe(6)

    await w.findAll('input.odm-price-input')[1]!.setValue('7')
    await w.get('button.odm-save').trigger('click')
    await flushPromises()
    expect(purchaseApi.updateItemPrices).toHaveBeenLastCalledWith(100, expect.any(Array), 6)
  })

  it('409 冲突：warning 提示「BOM 已更新」+ 触发重新拉单，不出成功提示', async () => {
    vi.mocked(purchaseApi.updateItemPrices).mockRejectedValue({ response: { status: 409 } })
    const w = mountModal(makeOrder())
    await editFirstPriceAndSave(w)

    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('BOM 已更新'), 'warning')
    // 父组件收到 saved 后会重新拉取订单详情（拿到最新明细与版本）
    expect(w.emitted('saved')).toEqual([[100]])
    expect(showToast).not.toHaveBeenCalledWith('单价已保存', 'success')
  })
})
