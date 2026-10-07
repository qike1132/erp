/**
 * ReportRecordPicker —— 聚合行还原出多条记录时的选择弹窗。
 *
 * 本文件前身是 OrderRecordTable.multiSku.test.ts（记录列表多 SKU 分行显示）。
 * 该主题组件已随 2026-10-06 记录查询 tab 收敛至 /report 而删除；本文件承接
 * /report 同层新主题：还原选择弹窗的列结构、按 action 渲染对应按钮、
 * pick 事件载荷是原始记录。
 */
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import PrimeVue from 'primevue/config'
import { plushCutePT } from '@/styles/primevue-pt'
import ReportRecordPicker from '@/views/report/components/ReportRecordPicker.vue'
import type { UnifiedRecord } from '@/api/order'

/** 还原出的两条订单记录（同组：同日+客户+产品） */
function record(id: number, orderNo: string, quantity: number): UnifiedRecord {
  return {
    id,
    record_type: 'order',
    order_no: orderNo,
    customer: 'MINISO国际',
    order_date: '2026-09-30 10:00',
    status: '待备货',
    product: { id: 1, name: '鲨鱼毛绒公仔', barcode: '690123', image: '' },
    quantity,
    deduct_quantity: 0,
    factories: ['东莞'],
    items: [{ id: id * 10, product_name: '鲨鱼毛绒公仔', quantity, note: id === 1 ? '首单' : '' }],
  }
}

const RECORDS = [record(1, 'PO-20260930-0013', 10000), record(2, 'PO-20260930-0014', 20000)]

function mountPicker(action: 'edit' | 'delete', records: UnifiedRecord[] = RECORDS) {
  return mount(ReportRecordPicker, {
    props: { open: true, records, action },
    global: {
      plugins: [[PrimeVue, { unstyled: true, pt: plushCutePT }]],
      stubs: {
        UiDialog: {
          template: '<div v-if="open" class="ui-dialog-stub"><slot /><slot name="footer" /></div>',
          props: ['open', 'title', 'maxWidthClass'],
        },
        FontAwesomeIcon: { template: '<i />' },
      },
    },
  })
}

describe('ReportRecordPicker —— 多条记录选择弹窗', () => {
  it('列结构：单号 / 时间 / 数量 / 状态 / 备注 / 操作', () => {
    const w = mountPicker('edit')

    expect(w.findAll('thead th').map((th) => th.text().trim()))
      .toEqual(['单号', '时间', '数量', '状态', '备注', '操作'])
  })

  it('每行渲染组内记录：单号与数量各归其列，状态备货 null → 留白', () => {
    const w = mountPicker('edit', [
      RECORDS[0]!,
      { ...RECORDS[1]!, record_type: 'stockin', status: null },
    ])

    const rows = w.findAll('tbody tr')
    expect(rows.length).toBe(2)
    expect(rows[0]!.text()).toContain('PO-20260930-0013')
    expect(rows[0]!.text()).toContain('10000')
    expect(rows[1]!.text()).not.toContain('待备货')

    // 备注列取 items[0].note
    expect(rows[0]!.text()).toContain('首单')
  })

  it('action=edit 只给编辑按钮；action=delete 只给删除按钮', () => {
    const editW = mountPicker('edit')
    expect(editW.findAll('.rp-btn-edit').length).toBe(2)
    expect(editW.findAll('.rp-btn-danger').length).toBe(0)

    const deleteW = mountPicker('delete')
    expect(deleteW.findAll('.rp-btn-danger').length).toBe(2)
    expect(deleteW.findAll('.rp-btn-edit').length).toBe(0)
  })

  it('点按钮 emit pick，载荷是原始记录对象（含 items / id）', async () => {
    const w = mountPicker('edit')

    await w.findAll('.rp-btn-edit')[1]!.trigger('click')

    const payload = w.emitted('pick')![0]![0] as UnifiedRecord
    expect(payload.id).toBe(2)
    expect(payload.order_no).toBe('PO-20260930-0014')
    expect(Array.isArray(payload.items)).toBe(true)
  })

  it('标题带上组内记录条数与动作名', () => {
    const w = mountPicker('edit')
    expect(w.props('records').length).toBe(2)
  })
})
