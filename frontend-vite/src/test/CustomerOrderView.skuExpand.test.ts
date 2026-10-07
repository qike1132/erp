/**
 * EditOrderModal 订单明细（SKU 表格）显隐守卫。
 *
 * 本文件前身是 CustomerOrderView SKU expand behavior（SubTask 7.4）：记录列表
 * 按 SKU 分行（组件 OrderRecordTable 已随 2026-10-06 记录查询 tab 收敛至 /report
 * 而删除，分行行为不再存在）+ 详情弹窗 SKU 表格用例。列表部分随之删除；
 * 详情弹窗部分改为**直接挂载迁移后的 views/report/components/EditOrderModal.vue**，
 * 继续锁「订单明细区块随 items.length 显隐」。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { reactive } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
  orderDetailMock: vi.fn(),
  auxAvailableStockinsMock: vi.fn(),
}))

vi.mock('@/api', () => ({
  orderApi: {
    detail: mocks.orderDetailMock,
    update: vi.fn(),
    updateDeduct: vi.fn(),
  },
  auxApi: {
    availableStockins: mocks.auxAvailableStockinsMock,
  },
}))

vi.mock('@tanstack/vue-query', () => ({
  useQuery: () => ({ data: { value: null } }),
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))

vi.mock('@/composables/useToast', () => ({
  showToast: vi.fn(),
}))

import EditOrderModal from '@/views/report/components/EditOrderModal.vue'
import type { OrderDetailData } from '@/views/report/composables/orderRecordTypes'

const stubs = {
  UiInput: { template: '<input />' },
  UiDatePicker: { template: '<input />' },
  UiButton: { template: '<button><slot /></button>' },
  UiDialog: {
    template: '<div v-if="open" class="ui-dialog-stub"><slot /><slot name="footer" /></div>',
    props: ['open', 'title', 'maxWidthClass'],
  },
  UiSelect: { template: '<div class="ui-select-stub" />' },
}

/** EditOrderModal 的必填 props（EditOrderModal.vue props 清单；editForm 是必填 v-model） */
function modalProps(detailData: OrderDetailData) {
  return {
    open: true,
    detailData,
    editForm: editForm(),
    availableStockin: 0,
    saving: false,
    deductRetryPending: false,
    getStatusClass: () => '',
    saveEditOrder: vi.fn(),
    retryDeductUpdate: vi.fn(),
  }
}

/** 编辑表单（v-model:editForm） */
function editForm(quantity = 10, deductQuantity = 0, note = '') {
  return reactive({ quantity, deductQuantity, note })
}

/** 构造 OrderDetailData：fixture 只填弹窗实际渲染的字段，缺省字段由类型断言补齐 */
function detailData(over: Record<string, unknown>): OrderDetailData {
  return {
    id: 1,
    order_no: 'ORD-001',
    customer: '客户A',
    order_date: '2024-01-01',
    product: { name: '产品A', barcode: '69001', id: 1 },
    quantity: 10,
    deduct_quantity: 0,
    status: '待备货',
    items: [],
    ...over,
  } as unknown as OrderDetailData
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.auxAvailableStockinsMock.mockResolvedValue([])
})

describe('EditOrderModal —— 订单明细（SKU 表格）显隐', () => {
  it('detailData.items.length > 1 时显示「订单明细」与全部 SKU 行', async () => {
    const wrapper = mount(EditOrderModal, {
      props: modalProps(detailData({
        items: [
          { id: 1, product_name: 'SKU1', product_barcode: 'B001', quantity: 5, deduct_quantity: 0, note: '' },
          { id: 2, product_name: 'SKU2', product_barcode: 'B002', quantity: 5, deduct_quantity: 0, note: '' },
        ],
      })),
      global: { stubs },
    })
    await flushPromises()

    const dialogText = wrapper.text()
    expect(dialogText).toContain('订单明细')
    expect(dialogText).toContain('2 个 SKU')

    // SKU details table should render 2 rows (one per SKU)
    const skuRows = wrapper.findAll('.oe-sku-table tbody tr')
    expect(skuRows.length).toBe(2)

    expect(dialogText).toContain('SKU1')
    expect(dialogText).toContain('SKU2')
  })

  it('detailData.items.length === 1 时隐藏 SKU 表格', async () => {
    const wrapper = mount(EditOrderModal, {
      props: modalProps(detailData({
        items: [{ id: 1, product_name: 'SKU1', quantity: 10 }],
      })),
      global: { stubs },
    })
    await flushPromises()

    expect(wrapper.find('.oe-sku-table').exists(), 'SKU table should be hidden for single-SKU detail').toBe(false)

    const dialogText = wrapper.text()
    expect(dialogText).not.toContain('订单明细')
    expect(dialogText).not.toContain('个 SKU')
  })

  it('detailData.items 为空数组时同样隐藏', async () => {
    const wrapper = mount(EditOrderModal, {
      props: modalProps(detailData({
        order_no: 'ORD-002',
        customer: '客户B',
        order_date: '2024-02-02',
        product: { name: '产品B', barcode: '69002', id: 2 },
        quantity: 7,
        items: [],
      })),
      global: { stubs },
    })
    await flushPromises()

    // Empty items array → v-if "detailData.items?.length > 1" is false → table hidden
    expect(wrapper.find('.oe-sku-table').exists(), 'SKU table should be hidden when items is empty').toBe(false)

    expect(wrapper.text()).not.toContain('订单明细')
  })
})
