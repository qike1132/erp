/**
 * 记录列表「产品」列的多 SKU 展示（方案 B：产品列堆叠显示全部 SKU）。
 *
 * 背景：订单/备货合并成一张表后，一行只显示**第一个 SKU 的产品名** + 订单**总数量**，
 * 其余 SKU（生产实例 PO-20260930-0013 有 3 个 SKU 各 10000）在列表里完全不可见。
 * 方案 B 把该订单的全部 SKU 名与各自数量堆叠渲染在产品列内，零交互、不新增列。
 *
 * 同时锁住备货行的操作列：`openDetail()` 一律调 `GET /orders/{id}`，而备货行的 id 是
 * `StockIn.id`（生产库实际 39268，订单 id 范围 68819~68915，查无此单 → 必然 404），
 * 且后端不存在备货详情端点，故备货行不提供「查看」按钮（与合并前备货页签无操作列一致）。
 */
import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import PrimeVue from 'primevue/config'
import { plushCutePT } from '@/styles/primevue-pt'
import OrderRecordTable from '@/views/customer-order/components/OrderRecordTable.vue'

/** 生产实例：PO-20260930-0013 / MINISO国际 / 3 个 SKU 各 10000，合计 30000 */
const MULTI_SKU_ORDER = {
  id: 68915,
  record_type: 'order',
  order_no: 'PO-20260930-0013',
  customer: 'MINISO国际',
  order_date: '2026-09-30 00:00',
  status: '待备货',
  product: { id: 1, name: '《蛋仔派对》市集拾趣系列 毛绒公仔挂件盲盒', barcode: '', image: '' },
  quantity: 30000,
  deduct_quantity: 0,
  factories: ['东莞', '湖北'],
  items: [
    { id: 901, product_id: 1, product_name: '《蛋仔派对》市集拾趣系列 毛绒公仔挂件盲盒', quantity: 10000 },
    { id: 902, product_id: 2, product_name: '鲨鱼', quantity: 10000 },
    { id: 903, product_id: 3, product_name: '《蛋仔派对》团子木鱼毛绒挂件盲盒-黄蛋 陈列样', quantity: 10000 },
  ],
}

/** 备货行：恒 1 个 SKU，id 来自 StockIn 表（与订单 id 不同序列） */
const STOCKIN_ROW = {
  id: 39268,
  record_type: 'stockin',
  order_no: 'BH-20260929-0001',
  customer: 'MINISO国际',
  order_date: '2026-09-29 20:14',
  status: null,
  product: { id: 1, name: '《蛋仔派对》市集拾趣系列 毛绒公仔挂件盲盒', barcode: '6901234567890', image: '' },
  quantity: 20000,
  deduct_quantity: 0,
  factories: ['东莞'],
  items: [
    { id: 39268, product_id: 1, product_name: '《蛋仔派对》市集拾趣系列 毛绒公仔挂件吸塑', quantity: 20000 },
  ],
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

describe('记录列表产品列 · 多 SKU 堆叠展示（方案 B）', () => {
  it('3 个 SKU 的订单行：产品列渲染 3 条 SKU 行，各带自己的名字与数量', () => {
    const wrapper = mountTable([MULTI_SKU_ORDER])

    const lines = wrapper.findAll('.co-sku-line')
    expect(lines.length).toBe(3)
    expect(lines.map((l) => l.find('.co-sku-name').text())).toEqual([
      '《蛋仔派对》市集拾趣系列 毛绒公仔挂件盲盒',
      '鲨鱼',
      '《蛋仔派对》团子木鱼毛绒挂件盲盒-黄蛋 陈列样',
    ])
    expect(lines.map((l) => l.find('.co-sku-qty').text())).toEqual(['10000', '10000', '10000'])
  })

  it('3 个 SKU 的订单行：数量列仍显示订单总数量，SKU 数量徽章仍为 3', () => {
    const wrapper = mountTable([MULTI_SKU_ORDER])

    const cells = wrapper.findAll('tbody td').map((td) => td.text())
    expect(cells).toContain('30000')
    // 徽章列（SKU 数量）在合并前后都保留，与堆叠展示并存
    expect(wrapper.find('.co-badge-tag').text()).toBe('3')
  })

  it('单 SKU 行：产品列只显示产品名，不渲染堆叠列表', () => {
    const wrapper = mountTable([STOCKIN_ROW])

    expect(wrapper.findAll('.co-sku-line').length).toBe(0)
    expect(wrapper.text()).toContain('《蛋仔派对》市集拾趣系列 毛绒公仔挂件盲盒')
    // 单 SKU 行保留条码副行（与合并前的产品列渲染一致）
    expect(wrapper.text()).toContain('6901234567890')
  })

  it('备货行不提供「查看」按钮（备货详情端点不存在，点了必然 404）', () => {
    const wrapper = mountTable([STOCKIN_ROW])

    expect(wrapper.findAll('.co-btn-info').length).toBe(0)
    expect(wrapper.findAll('.co-btn-danger').length).toBe(0)
  })

  it('订单行仍然提供「查看」与「删除」', () => {
    const wrapper = mountTable([MULTI_SKU_ORDER])

    expect(wrapper.findAll('.co-btn-info').length).toBe(1)
    expect(wrapper.findAll('.co-btn-danger').length).toBe(1)
  })

  it('订单+备货混排时：只有订单行有操作按钮，产品列只对多 SKU 行堆叠', () => {
    const wrapper = mountTable([MULTI_SKU_ORDER, STOCKIN_ROW])

    expect(wrapper.findAll('tbody tr').length).toBe(2)
    expect(wrapper.findAll('.co-sku-line').length).toBe(3)
    expect(wrapper.findAll('.co-btn-info').length).toBe(1)
  })
})
