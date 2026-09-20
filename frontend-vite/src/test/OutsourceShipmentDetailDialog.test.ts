/**
 * OutsourceShipmentDetailDialog 发货单明细回归
 *
 * 重点：明细表新增「订单总数」列（订单要求的该工序总数量），位于「发货数量」左侧；
 * 工序被删除时 order_qty 为空，该列显示 '-'。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import OutsourceShipmentDetailDialog from '@/views/outsource/components/OutsourceShipmentDetailDialog.vue'

const shipmentDetailMock = vi.fn()

vi.mock('@/composables/useToast', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))
vi.mock('@/api/outsource', () => ({
  outsourceApi: {
    shipmentDetail: (...args: unknown[]) => shipmentDetailMock(...args),
  },
}))

function item(over: Record<string, unknown> = {}) {
  return {
    id: 1,
    process_id: 101,
    product_id: 1,
    product_name: 'SKU-A',
    process_type: '电绣',
    order_qty: 1000,
    shipped_quantity: 600,
    received_quantity: 0,
    ...over,
  }
}

function shipment(items: unknown[]) {
  return {
    id: 1,
    shipment_no: 'FH-20260920-0001',
    order_id: 1,
    customer: '客户A',
    status: 'shipped',
    shipped_at: '2026-09-20 10:00',
    received_at: null,
    shipped_by: 'admin',
    received_by: null,
    remark: null,
    create_time: '2026-09-20 10:00',
    item_count: items.length,
    total_shipped: 600,
    items,
  }
}

async function mountDialog(items: unknown[]) {
  shipmentDetailMock.mockResolvedValue(shipment(items))
  const wrapper = mount(OutsourceShipmentDetailDialog, {
    props: { open: false, shipmentId: 1 },
    global: {
      stubs: {
        FontAwesomeIcon: { template: '<i />' },
        UiDialog: { template: '<div class="ui-dialog"><slot /><slot name="footer" /></div>' },
        UiButton: { template: '<button><slot /></button>' },
        UiSpinner: { template: '<div />' },
      },
    },
  })
  await wrapper.setProps({ open: true })
  await flushPromises()
  return wrapper
}

/** 表头文本 */
function headers(wrapper: Awaited<ReturnType<typeof mountDialog>>): string[] {
  return wrapper.findAll('.osdd-table thead th').map((th) => th.text())
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('OutsourceShipmentDetailDialog 发货单明细', () => {
  it('新增「订单总数」列，且位于「发货数量」左侧', async () => {
    const wrapper = await mountDialog([item()])
    const ths = headers(wrapper)
    expect(ths).toContain('订单总数')
    expect(ths.indexOf('订单总数')).toBe(ths.indexOf('发货数量') - 1)
  })

  it('订单总数取该工序的订单数量并格式化', async () => {
    const wrapper = await mountDialog([item({ order_qty: 12345 })])
    const cells = wrapper.findAll('.osdd-table tbody tr:first-child td')
    // 列序：# | SKU | 工序 | 订单总数 | 发货数量 | 收货数量 | 未收货
    expect(cells[3]!.text()).toBe('12,345')
    expect(cells[4]!.text()).toBe('600')
  })

  it('工序已删除（order_qty 为空）时显示 -', async () => {
    const wrapper = await mountDialog([item({ process_id: null, order_qty: null })])
    const cells = wrapper.findAll('.osdd-table tbody tr:first-child td')
    expect(cells[3]!.text()).toBe('-')
  })

  it('既有列与合计行不受影响', async () => {
    const wrapper = await mountDialog([item({ received_quantity: 200 })])
    const cells = wrapper.findAll('.osdd-table tbody tr:first-child td')
    // 未收货 = 600 - 200
    expect(cells[6]!.text()).toBe('400')
    expect(wrapper.find('.osdd-foot').text()).toContain('共 1 道工序')
  })
})
