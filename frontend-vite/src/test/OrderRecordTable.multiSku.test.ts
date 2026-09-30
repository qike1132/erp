/**
 * 记录列表的多 SKU 分行显示（每个 SKU 占一行）。
 *
 * 需求：多 SKU 订单的「产品名称」与「数量」各自落在自己的列、自己那一行；
 * 订单级字段（时间/编号/客户）跨该订单的 SKU 行合并成一个格。**不产出合计行**
 * （2026-10-01 用户要求删除），故订单总量不在列表里显示。
 *
 * 同时锁住两件容易被改坏的事：
 * ① 相邻订单即使时间/客户完全相同，也**不会**被并成一个大格；
 * ② 操作列发出的必须是**原始订单记录**（不是摊平后的行），否则详情/删除会拿到错误的 id。
 */
import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import PrimeVue from 'primevue/config'
import { plushCutePT } from '@/styles/primevue-pt'
import OrderRecordTable from '@/views/customer-order/components/OrderRecordTable.vue'

/** 生产实例：PO-20260930-0013 / MINISO国际 / 3 个 SKU 各 10000，订单总量 30000 */
const MULTI_SKU_ORDER = {
  id: 68915,
  record_type: 'order',
  order_no: 'PO-20260930-0013',
  customer: 'MINISO国际',
  order_date: '2026-09-30 00:00',
  status: '待备货',
  product: { id: 1, name: '首个 SKU 的产品名', barcode: '', image: '' },
  quantity: 30000,
  deduct_quantity: 0,
  factories: ['东莞', '湖北'],
  items: [
    { id: 901, product_name: '《蛋仔派对》市集拾趣系列 毛绒公仔挂件盲盒', quantity: 10000 },
    { id: 902, product_name: '鲨鱼', quantity: 10000 },
    { id: 903, product_name: '《蛋仔派对》团子木鱼毛绒挂件盲盒-黄蛋 陈列样', quantity: 10000 },
  ],
}

/** 紧跟其后的另一笔订单：**时间与客户都相同**（生产数据里这几笔都是 2026-09-30 00:00 / MINISO国际） */
const SIBLING_ORDER = {
  ...MULTI_SKU_ORDER,
  id: 68999,
  order_no: 'PO-20260930-0012',
  quantity: 20000,
  items: [
    { id: 911, product_name: '测试', quantity: 10000 },
    { id: 912, product_name: '鲨鱼', quantity: 10000 },
  ],
}

/** 单 SKU 订单 */
const SINGLE_SKU_ORDER = {
  ...MULTI_SKU_ORDER,
  id: 68916,
  order_no: 'PO-20260930-0014',
  customer: '网易',
  product: { id: 1, name: '测试', barcode: '69001', image: '' },
  quantity: 10000,
  items: [{ id: 910, product_name: '测试', quantity: 10000 }],
}

/** 备货行（恒 1 个 SKU，无操作入口） */
const STOCKIN_ROW = {
  ...MULTI_SKU_ORDER,
  id: 39268,
  record_type: 'stockin',
  order_no: 'BH-20260929-0001',
  product: { id: 1, name: '鲨鱼', barcode: '6901234567890', image: '' },
  quantity: 10000,
  items: [{ id: 39268, product_name: '鲨鱼', quantity: 10000 }],
}

function mountTable(rows: unknown[], canDelete = true) {
  return mount(OrderRecordTable, {
    props: {
      orderRecords: rows as never,
      isLoadingRecords: false,
      isFetchingRecords: false,
      errorMessage: '',
      totalPages: 1,
      totalRecords: rows.length,
      perPage: 20,
      canDelete,
      fetchOrders: vi.fn(),
    },
    global: { plugins: [[PrimeVue, { unstyled: true, pt: plushCutePT }]] },
  })
}

/** 表头顺序固定，末三列永不参与合并 */
const TAIL_COLUMNS = ['产品名称', '数量', '操作'] as const

/**
 * 取末三列（产品名称/数量/操作）在每一行的文本。
 *
 * 不能按固定下标取格：合并后，组内第 2..N 行的前三格不再渲染，`td[3]` 就落到了别的列上。
 * 只有前三列（时间/编号/客户）会合并，故用「从行尾往前数」定位，并用格数不变量（6 或 3）兜底。
 */
function tailColumnTexts(wrapper: ReturnType<typeof mountTable>, header: typeof TAIL_COLUMNS[number]): string[] {
  const offset = TAIL_COLUMNS.indexOf(header)
  expect(offset, `${header} 应在末三列里`).toBeGreaterThan(-1)
  return wrapper.findAll('tbody tr').map((tr) => {
    const tds = tr.findAll('td')
    expect([3, 6], '每行应是 6 格，或被合并掉前三格后的 3 格').toContain(tds.length)
    return tds[tds.length - 3 + offset]?.text().trim() ?? ''
  })
}

/** 组首行 = 第一格带 rowspan 的行（每个订单/备货的 SKU 组第一行） */
function groupLeadRows(wrapper: ReturnType<typeof mountTable>) {
  return wrapper.findAll('tbody tr').filter((tr) => tr.findAll('td')[0]?.attributes('rowspan') !== undefined)
}

/** 取组首行里某一列（前三列之一）的文本 */
function mergedCellText(tr: ReturnType<typeof groupLeadRows>[number], header: '时间' | '编号' | '客户'): string {
  const idx = ['时间', '编号', '客户'].indexOf(header)
  return tr.findAll('td')[idx]?.text().trim() ?? ''
}

describe('记录列表 · 多 SKU 分行显示', () => {
  it('列结构：时间 / 编号 / 客户 / 产品名称 / 数量 / 操作', () => {
    const wrapper = mountTable([MULTI_SKU_ORDER])
    expect(wrapper.findAll('thead th').map((th) => th.text().trim()))
      .toEqual(['时间', '编号', '客户', '产品名称', '数量', '操作'])
  })

  it('3 个 SKU 摊成 3 行：每行产品名称是该 SKU 自己的名字，数量落在数量列', () => {
    const wrapper = mountTable([MULTI_SKU_ORDER])

    expect(tailColumnTexts(wrapper, '产品名称')).toEqual([
      '《蛋仔派对》市集拾趣系列 毛绒公仔挂件盲盒',
      '鲨鱼',
      '《蛋仔派对》团子木鱼毛绒挂件盲盒-黄蛋 陈列样',
    ])
    expect(tailColumnTexts(wrapper, '数量')).toEqual(['10000', '10000', '10000'])
  })

  it('订单级三列跨该订单的 SKU 行合并（rowspan=3，不含合计行）', () => {
    const wrapper = mountTable([MULTI_SKU_ORDER])
    const leads = groupLeadRows(wrapper)
    expect(leads.length, '应有 1 个组首行').toBe(1)

    const cells = leads[0]!.findAll('td')
    // 前三格是合并格；合并数 = 该订单的 SKU 行数
    expect(cells[0]!.attributes('rowspan')).toBe('3')
    expect(cells[1]!.attributes('rowspan')).toBe('3')
    expect(cells[2]!.attributes('rowspan')).toBe('3')
    // 产品名称与数量不合并（每个 SKU 各一格）
    expect(cells[3]!.attributes('rowspan')).toBeUndefined()
    expect(cells[4]!.attributes('rowspan')).toBeUndefined()

    // 合并文本只在该组渲染一次
    expect(mergedCellText(leads[0]!, '时间')).toBe('2026-09-30 00:00')
    expect(mergedCellText(leads[0]!, '编号')).toContain('PO-20260930-0013')
    expect(mergedCellText(leads[0]!, '客户')).toBe('MINISO国际')
  })

  it('相邻订单时间与客户完全相同，也不会被并成一个大格', () => {
    // 这是「按值合并」的真实风险：PO-20260930-0011/0012/0013 的日期都是 2026-09-30 00:00
    const wrapper = mountTable([MULTI_SKU_ORDER, SIBLING_ORDER])

    expect(wrapper.findAll('tbody tr').length, '3 行 + 2 行').toBe(5)

    // 两笔订单各有一个组首行；第一笔的合并数必须只是它自己的 3 行，不能把下一笔算进来
    const leads = groupLeadRows(wrapper)
    expect(leads.length, '两笔订单应各有一个组首行（说明没有并成一个大格）').toBe(2)
    expect(leads[0]!.findAll('td')[0]!.attributes('rowspan')).toBe('3')
    expect(mergedCellText(leads[0]!, '编号')).toContain('PO-20260930-0013')
    expect(mergedCellText(leads[1]!, '编号')).toContain('PO-20260930-0012')
  })

  it('单 SKU 订单只 1 行', () => {
    const wrapper = mountTable([SINGLE_SKU_ORDER])

    expect(wrapper.findAll('tbody tr').length).toBe(1)
    expect(tailColumnTexts(wrapper, '产品名称')).toEqual(['测试'])
    expect(tailColumnTexts(wrapper, '数量')).toEqual(['10000'])
  })

  it('备货行的产品名称与数量各归其列，且没有操作入口', () => {
    const wrapper = mountTable([STOCKIN_ROW])

    expect(tailColumnTexts(wrapper, '产品名称')).toEqual(['鲨鱼'])
    expect(tailColumnTexts(wrapper, '数量')).toEqual(['10000'])
    expect(wrapper.findAll('.co-btn-info').length).toBe(0)
    expect(wrapper.findAll('.co-btn-danger').length).toBe(0)
  })

  it('操作列发出的是原始订单记录（含 items），不是摊平后的行', () => {
    const wrapper = mountTable([MULTI_SKU_ORDER])
    const viewBtn = wrapper.findAll('.co-btn-info')[0]!
    void viewBtn.trigger('click')

    const emitted = wrapper.emitted('view-detail')
    expect(emitted, 'view-detail 应被发出').toBeTruthy()
    const payload = emitted![0]![0] as Record<string, unknown>
    expect(payload.order_no).toBe('PO-20260930-0013')
    expect(Array.isArray(payload.items), '必须是原始订单记录（带 items），否则详情拿不到 SKU 明细').toBe(true)
  })

  it('每个 SKU 行都有查看与删除按钮（可按任意一行操作该订单）', () => {
    const wrapper = mountTable([MULTI_SKU_ORDER])

    // 每个 SKU 行各有一个入口
    expect(wrapper.findAll('.co-btn-info').length).toBe(3)
    expect(wrapper.findAll('.co-btn-danger').length).toBe(3)
  })

  it('无 items 的订单按自身回退为 1 行（不整单消失）', () => {
    const noItems = { ...SINGLE_SKU_ORDER, items: undefined } as unknown as Record<string, unknown>
    const wrapper = mountTable([noItems])

    expect(wrapper.findAll('tbody tr').length).toBe(1)
    expect(tailColumnTexts(wrapper, '产品名称')).toEqual(['测试'])
  })
})
