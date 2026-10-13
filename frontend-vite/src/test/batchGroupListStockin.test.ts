import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import BatchGroupList from '@/views/batch/components/BatchGroupList.vue'

const updateBatchNo = vi.fn().mockResolvedValue({ updated_count: 1 })
vi.mock('@/api', () => ({ orderBatchApi: { updateBatchNo: (...a: unknown[]) => updateBatchNo(...a) } }))
vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))

const stockinGroup = [{
  customer: 'MINISO国际',
  products: [{
    key: 'p1', productName: '产品X', productBarcode: '690',
    orders: [{
      id: 7, order_no: 'SI-7', customer: 'MINISO国际', order_date: '2026-10-01',
      product_id: 1, product_name: '产品X', product_barcode: '690', quantity: 5,
      deducted_qty: 0, shipped_qty: 0, status: null, computed_status: null,
      batch_no: null, batch_completed_at: null, is_locked: null, record_type: 'stockin',
    }],
  }],
}]

describe('BatchGroupList 备货 chip', () => {
  beforeEach(() => updateBatchNo.mockClear())

  it('备货 chip 也渲染批次号输入框', () => {
    const w = mount(BatchGroupList, { props: { grouped: stockinGroup } })
    expect(w.find('.bt-batch-input').exists()).toBe(true)
  })

  it('备货保存时带 record_type=stockin', async () => {
    const w = mount(BatchGroupList, { props: { grouped: stockinGroup } })
    const input = w.find('.bt-batch-input')
    await input.setValue('B9')
    await input.trigger('keydown.enter')
    expect(updateBatchNo).toHaveBeenCalledWith(7, { batch_no: 'B9', record_type: 'stockin' })
  })

  it('订单与备货 id 撞号时各按自身 record_type 保存（复合键防串扰）', async () => {
    const row = (record_type: 'order' | 'stockin', order_no: string) => ({
      id: 7, order_no, customer: 'MINISO国际', order_date: '2026-10-01', product_id: 1,
      product_name: '产品Y', product_barcode: '691', quantity: 2, deducted_qty: 0, shipped_qty: 0,
      status: null, computed_status: null, batch_no: null, batch_completed_at: null,
      is_locked: null, record_type,
    })
    const mixed = [{
      customer: 'MINISO国际',
      products: [{
        key: 'p2', productName: '产品Y', productBarcode: '691',
        orders: [row('order', 'PO-7'), row('stockin', 'SI-7')],
      }],
    }]
    const w = mount(BatchGroupList, { props: { grouped: mixed } })
    const inputs = w.findAll('.bt-batch-input')
    expect(inputs.length).toBe(2)
    await inputs[1]!.setValue('BS')
    await inputs[1]!.trigger('keydown.enter')
    expect(updateBatchNo).toHaveBeenCalledTimes(1)
    expect(updateBatchNo).toHaveBeenCalledWith(7, { batch_no: 'BS', record_type: 'stockin' })
  })
})
