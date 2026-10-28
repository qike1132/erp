/**
 * 采购中心三个页签：订单号列回归锁（2026-09-30）。
 *
 * 背景：三个列表接口本就返回 order_no，但屏上表格从未定义这一列
 * （「已完成」的导出里其实已有「订单号」，只有屏上落后）。
 * 现按变体 A 统一叫「订单号」，置于时间列之后（与该页导出的列序一致）。
 *
 * 三个页签的单号含义不同——待处理是客户订单（PO），进行中/已完成是采购订单
 * （2026-10-10 起也统一为 PO；此前为 CG）。故本文件的数据用各自真实的前缀。
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ActiveOrdersPanel from '@/views/purchase/components/ActiveOrdersPanel.vue'
import CompletedOrdersPanel from '@/views/purchase/components/CompletedOrdersPanel.vue'

function mountActive(orders: unknown[], unprocessedOrders: unknown[] = []) {
  return mount(ActiveOrdersPanel, {
    props: {
      orders,
      unprocessedOrders,
      loading: false,
      total: orders.length,
      currentPage: 1,
      totalPages: 1,
      selectedIds: [],
      allSelected: false,
    } as never,
    global: { stubs: { UiCheckbox: true, UiPagination: true } },
  })
}

function mountCompleted(orders: unknown[]) {
  return mount(CompletedOrdersPanel, {
    props: {
      orders,
      loading: false,
      total: orders.length,
      currentPage: 1,
      totalPages: 1,
      hasFilter: false,
      filters: {},
    } as never,
    global: { stubs: { UiPagination: true } },
  })
}

const unprocessedRow = {
  composite_id: 'c1',
  id: 1,
  order_no: 'PO-20260929-0014',
  record_type: 'order',
  order_date: '2026-09-29',
  create_time: '2026-09-29T10:00:00',
  customer: 'MINISO国内',
  product_name: 'X',
  quantity: 30,
  has_bom: true,
  items: [],
  barcode: '690001',
  sku_count: 1,
}

const activeRow = {
  id: 2,
  order_no: 'PO-20260928-0001',
  create_time: '2026-09-28T10:00:00',
  customer_name: 'MINISO国内',
  product_name: 'X',
  quantity: 100,
  sku_items: [],
  items: [],
}

const completedRow2Sku = {
  id: 3,
  order_no: 'PO-20260928-0002',
  completed_at: '2026-09-28T17:20:00',
  customer_name: 'MINISO国内',
  sku_items: [
    { product_name: 'A', quantity: 10 },
    { product_name: 'B', quantity: 20 },
  ],
  items: [],
}

describe('采购中心 · 待生成行（并入待生产面板同表）', () => {
  it('表头含「订单号」且紧随时间列', () => {
    const headers = mountActive([], [unprocessedRow]).findAll('th').map((th) => th.text())
    expect(headers).toContain('订单号')
    expect(headers.indexOf('订单号')).toBe(headers.indexOf('下单时间') + 1)
  })

  it('行内渲染客户订单号；缺 BOM 时操作列提示无法下单', () => {
    const text = mountActive([], [{ ...unprocessedRow, has_bom: false }]).text()
    expect(text).toContain('PO-20260929-0014')
    expect(text).toContain('未配置BOM，无法下单')
    expect(text).toContain('请联系产品管理员')
  })

  it('有 product_manage 时才渲染配置入口，并按行发出续提事件', async () => {
    const wrapper = mountActive([], [{ ...unprocessedRow, has_bom: false }])
    await wrapper.setProps({ canManageBom: true })
    const button = wrapper.find('.pc-nobom-action button')
    expect(button.text()).toBe('配置 BOM 并下单')
    await button.trigger('click')
    expect(wrapper.emitted('configureBom')?.[0]?.[0]).toMatchObject({
      composite_id: 'c1', has_bom: false,
    })
  })
})

describe('采购中心 · 进行中面板', () => {
  it('表头含「订单号」且紧随时间列', () => {
    const headers = mountActive([activeRow]).findAll('th').map((th) => th.text())
    expect(headers).toContain('订单号')
    expect(headers.indexOf('订单号')).toBe(headers.indexOf('下单时间') + 1)
  })

  it('行内渲染采购订单号', () => {
    expect(mountActive([activeRow]).text()).toContain('PO-20260928-0001')
  })

  it('类型列按来源显示：有来源客户订单 → 订单；无 → 备货', () => {
    expect(mountActive([{ ...activeRow, source_order_no: 'PO-20260901-0001' }]).text()).toContain('订单')
    expect(mountActive([{ ...activeRow, source_order_no: '' }]).text()).toContain('备货')
  })
})

describe('采购中心 · 已完成面板', () => {
  it('表头含「订单号」且紧随时间列', () => {
    const headers = mountCompleted([completedRow2Sku]).findAll('th').map((th) => th.text())
    expect(headers).toContain('订单号')
    expect(headers.indexOf('订单号')).toBe(headers.indexOf('完成时间') + 1)
  })

  it('行内渲染采购订单号', () => {
    expect(mountCompleted([completedRow2Sku]).text()).toContain('PO-20260928-0002')
  })

  it('多 SKU：订单号是订单级单元格（rowspan 覆盖整单），不在每个 SKU 行重复', () => {
    const wrapper = mountCompleted([completedRow2Sku])
    const rows = wrapper.findAll('tbody tr')
    expect(rows.length).toBe(2) // 2 个 SKU 行
    const headers = wrapper.findAll('th').length

    // 首行：每列都有格；订单号格带 rowspan=2
    const first = rows[0]!.findAll('td')
    expect(first.length).toBe(headers)
    const noCell = first.find((td) => td.text().includes('PO-20260928-0002'))
    expect(noCell, '首行应含订单号单元格').toBeTruthy()
    expect(noCell!.attributes('rowspan')).toBe('2')

    // 第 2 行：订单级格（完成时间/订单号/客户/操作 = 4 个）由 rowspan 覆盖，只剩 产品/数量
    const second = rows[1]!.findAll('td')
    expect(second.length).toBe(headers - 4)
    expect(rows[1]!.text()).not.toContain('PO-20260928-0002')
  })
})
