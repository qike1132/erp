/**
 * 采购单详情「单价补录」回归测试。
 *
 * 审计待核实 #1：一键生成路径没有价格来源（BOM 行无价字段），unit_price 恒写 0；
 * 更新请求原本不带 items 字段，前端也没有录入 UI → 采购单价生成后**永久为 0**，
 * 采购单金额与供应商金额汇总恒为 0。
 *
 * 契约：
 *   C1 每行单价可编辑，默认显示库里已存值；
 *   C2 只提交**改动过**的行（未改动的行不进请求体，后端也就不会重算它们）；
 *   C3 非法输入（负数/非数字）拦在前端，不提交；
 *   C4 保存成功后通知父组件刷新（否则弹窗仍显示旧金额）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
  updateItemPrices: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('@/api', () => ({
  purchaseApi: {
    updateItemPrices: mocks.updateItemPrices,
  },
}))

vi.mock('@/composables/useToast', () => ({
  showToast: mocks.showToast,
}))

// 组件内用的是 `import UiDialog from '@/components/ui/UiDialog.vue'`，stub 掉避免弹窗依赖
const stubs = {
  UiDialog: { template: '<div class="ui-dialog-stub"><slot name="footer" /><slot /></div>' },
}

import OrderDetailModal from '@/views/purchase/components/OrderDetailModal.vue'
import type { PurchaseOrder } from '@/types'

function makeOrder(overrides: Partial<PurchaseOrder> = {}): PurchaseOrder {
  return {
    id: 100,
    order_no: 'CG-20261021-0001',
    status: 'pending',
    total_amount: 0,
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

function priceInputs(wrapper: ReturnType<typeof mountModal>) {
  return wrapper.findAll('input.odm-price-input')
}

function saveButton(wrapper: ReturnType<typeof mountModal>) {
  return wrapper.get('button.odm-save')
}

beforeEach(() => {
  mocks.updateItemPrices.mockReset()
  mocks.showToast.mockReset()
})

describe('OrderDetailModal 单价补录', () => {
  it('每行单价默认显示库里已存值', () => {
    const w = mountModal(makeOrder())
    const inputs = priceInputs(w)
    expect(inputs).toHaveLength(2)
    expect((inputs[0]!.element as HTMLInputElement).value).toBe('0')
    expect((inputs[1]!.element as HTMLInputElement).value).toBe('5')
  })

  it('只提交改动过的行，并带上订单 id', async () => {
    mocks.updateItemPrices.mockResolvedValue({ success: true })
    const w = mountModal(makeOrder())

    await priceInputs(w)[0]!.setValue('3.5')
    await saveButton(w).trigger('click')
    await flushPromises()

    expect(mocks.updateItemPrices).toHaveBeenCalledTimes(1)
    expect(mocks.updateItemPrices).toHaveBeenCalledWith(100, [{ id: 1, unit_price: 3.5 }])
    expect(mocks.showToast).toHaveBeenCalledWith('单价已保存', 'success')
    expect(w.emitted('saved')).toEqual([[100]])
  })

  it('没有改动时保存按钮禁用、不会发请求', async () => {
    const w = mountModal(makeOrder())
    expect(saveButton(w).attributes('disabled')).toBeDefined()

    await saveButton(w).trigger('click')
    await flushPromises()
    expect(mocks.updateItemPrices).not.toHaveBeenCalled()
  })

  it('负数单价拦在前端：不提交，只报错', async () => {
    const w = mountModal(makeOrder())

    await priceInputs(w)[0]!.setValue('-1')
    await saveButton(w).trigger('click')
    await flushPromises()

    expect(mocks.updateItemPrices).not.toHaveBeenCalled()
    expect(mocks.showToast).toHaveBeenCalledWith('单价必须是大于等于 0 的数字', 'error')
  })

  it('保存失败时提示错误且不触发刷新', async () => {
    mocks.updateItemPrices.mockRejectedValue(new Error('单价不能为负数'))
    const w = mountModal(makeOrder())

    await priceInputs(w)[0]!.setValue('2')
    await saveButton(w).trigger('click')
    await flushPromises()

    expect(mocks.showToast).toHaveBeenCalledWith('单价不能为负数', 'error')
    expect(w.emitted('saved')).toBeUndefined()
  })

  it('行金额随输入即时重算（单价 × 数量）', async () => {
    const w = mountModal(makeOrder())
    await priceInputs(w)[0]!.setValue('2.5')

    const amounts = w.findAll('td.odm-td-amount').map((td) => td.text())
    // 2.5 × 10 = 25；第二行 5 × 4 = 20
    expect(amounts).toEqual(['25', '20'])
  })
})
