/**
 * 批次页「清空批次号」必须真的落库为 NULL（上线前审计 2026-11-16 Medium 3）。
 *
 * 现场：`saveBatchNo` 在输入框被删空时直接 return（静默丢弃），随后 blur/enter
 * 又把旧值显示回来——用户清不掉批次号，且没有任何提示。后端早已支持传 null
 * （schemas/order_batch.py 的 BatchNoUpdate；计划
 * docs/superpowers/plans/2026-10-13-stockin-batch-no.md「清空批次号（传 null）
 * 备货也要能落库为 NULL」）。
 *
 * 锁两件事：清空 → 提交 `batch_no: null`；值没变 → 不发请求（原有早退不得被删掉）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import BatchGroupList from '@/views/batch/components/BatchGroupList.vue'

const updateBatchNo = vi.fn().mockResolvedValue({ updated_count: 1 })
vi.mock('@/api', () => ({ orderBatchApi: { updateBatchNo: (...args: unknown[]) => updateBatchNo(...args) } }))
vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))

function groupWith(batchNo: string | null, recordType: 'order' | 'stockin' = 'stockin') {
  return [{
    customer: 'MINISO国际',
    products: [{
      key: 'p1',
      productName: '产品X',
      productBarcode: '690',
      orders: [{
        id: 9,
        order_no: 'SI-9',
        customer: 'MINISO国际',
        order_date: '2026-10-01',
        product_id: 1,
        product_name: '产品X',
        product_barcode: '690',
        quantity: 5,
        deducted_qty: 0,
        shipped_qty: 0,
        status: null,
        computed_status: null,
        batch_no: batchNo,
        batch_completed_at: null,
        is_locked: null,
        record_type: recordType,
      }],
    }],
  }]
}

describe('BatchGroupList 清空批次号', () => {
  beforeEach(() => updateBatchNo.mockClear())

  it('输入框删空后提交 batch_no: null（不得静默丢弃）', async () => {
    const wrapper = mount(BatchGroupList, { props: { grouped: groupWith('B-OLD') } })
    const input = wrapper.find('.bt-batch-input')

    await input.trigger('focus')
    await input.setValue('')
    await input.trigger('keydown.enter')

    expect(updateBatchNo).toHaveBeenCalledWith(9, { batch_no: null, record_type: 'stockin' })
  })

  it('订单行清空同样提交 null（record_type=order）', async () => {
    const wrapper = mount(BatchGroupList, { props: { grouped: groupWith('B-OLD', 'order') } })
    const input = wrapper.find('.bt-batch-input')

    await input.trigger('focus')
    await input.setValue('')
    await input.trigger('keydown.enter')

    expect(updateBatchNo).toHaveBeenCalledWith(9, { batch_no: null, record_type: 'order' })
  })

  it('值未变化时不发请求（保留「与原始值相同则不动」的早退）', async () => {
    const wrapper = mount(BatchGroupList, { props: { grouped: groupWith('B-OLD') } })
    const input = wrapper.find('.bt-batch-input')

    await input.trigger('focus')
    await input.setValue('B-OLD')
    await input.trigger('keydown.enter')

    expect(updateBatchNo).not.toHaveBeenCalled()
  })
})
