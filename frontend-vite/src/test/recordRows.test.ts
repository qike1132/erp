/**
 * 记录列表的行摊平（多 SKU 分行的数据准备）—— 纯函数，先于实现写。
 *
 * 背景：一张订单可含多个 SKU，而 `GET /orders/records` 一行一个订单（items[] 里挂 SKU）。
 * 要把「每个 SKU 的产品名称与数量各自落在产品名称列/数量列」，必须摊平成一行一 SKU。
 *
 * 摊平后每条订单产出 N 行（N = SKU 数），**不产出合计行**（2026-10-01 用户要求删除：
 * 合计行左侧三个格被合并格盖住、只在右侧显示「合计 30000」，读起来是多余的一行）。
 * 代价是订单总量不再出现在列表里 —— 各 SKU 数量仍在，总量可在详情弹窗查看。
 *
 * - 订单级字段（时间/编号/客户）在每行都带上真值，供组件渲染；
 * - `_g` 是同订单恒等的**分组键**，供表格做跨行合并。
 */
import { describe, expect, it } from 'vitest'
import { flattenRecordRows } from '@/views/customer-order/composables/recordRows'
import type { OrderRecord } from '@/views/customer-order/composables/types'

/** 生产实例：PO-20260930-0013 / MINISO国际 / 3 个 SKU 各 10000，订单总量 30000 */
const ORDER_3SKU = {
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
} as unknown as OrderRecord

/** 单 SKU 订单 */
const ORDER_1SKU = {
  id: 68916,
  record_type: 'order',
  order_no: 'PO-20260930-0014',
  customer: '网易',
  order_date: '2026-09-30 00:00',
  product: { id: 1, name: '测试', barcode: '69001', image: '' },
  quantity: 10000,
  items: [{ id: 910, product_name: '测试', quantity: 10000 }],
} as unknown as OrderRecord

/** 备货行（恒 1 个 SKU，无操作列入口） */
const STOCKIN = {
  id: 39268,
  record_type: 'stockin',
  order_no: 'BH-20260929-0001',
  customer: 'MINISO国际',
  order_date: '2026-09-28 17:28',
  product: { id: 2, name: '鲨鱼', barcode: '', image: '' },
  quantity: 10000,
  items: [{ id: 39268, product_name: '鲨鱼', quantity: 10000 }],
} as unknown as OrderRecord

describe('摊平记录行（多 SKU 分行）', () => {
  it('3 个 SKU 的订单摊成 3 行，每行数量取该 SKU 自己的数量（不产出合计行）', () => {
    const rows = flattenRecordRows([ORDER_3SKU])

    expect(rows.length).toBe(3)
    expect(rows.map((r) => r.product_name)).toEqual([
      '《蛋仔派对》市集拾趣系列 毛绒公仔挂件盲盒',
      '鲨鱼',
      '《蛋仔派对》团子木鱼毛绒挂件盲盒-黄蛋 陈列样',
    ])
    expect(rows.map((r) => r.quantity)).toEqual([10000, 10000, 10000])
  })

  it('同一订单的 SKU 行共享同一个分组键（跨行合并的前提）', () => {
    const rows = flattenRecordRows([ORDER_3SKU])

    const skuKeys = rows.map((r) => r._g)
    expect(new Set(skuKeys).size, '同一订单的 SKU 行分组键应一致').toBe(1)
    expect(skuKeys[0], '分组键应含来源与 id，不能只用时间/客户这类会跨订单重复的值')
      .toBe(`order#${ORDER_3SKU.id}`)
  })

  it('不同订单的分组键不同 —— 即使时间与客户都一样（否则跨订单会被误并）', () => {
    // 生产数据里 PO-20260930-0011/0012/0013 的时间都是 2026-09-30 00:00，客户也可能重复
    const sibling = { ...ORDER_3SKU, id: 68999, order_no: 'PO-20260930-0012', customer: 'MINISO国际' } as OrderRecord
    const rows = flattenRecordRows([ORDER_3SKU, sibling])

    const g1 = rows.find((r) => r.order_no === 'PO-20260930-0013')!._g
    const g2 = rows.find((r) => r.order_no === 'PO-20260930-0012')!._g
    expect(g1).not.toBe(g2)
  })

  it('订单级字段在每一行都带上真值（时间/编号/客户），供各行渲染', () => {
    const rows = flattenRecordRows([ORDER_3SKU])

    expect(rows.length, '先锁行数，避免空数组让下面的循环真空通过').toBe(3)
    for (const r of rows) {
      expect(r.order_date).toBe('2026-09-30 00:00')
      expect(r.order_no).toBe('PO-20260930-0013')
      expect(r.customer).toBe('MINISO国际')
      expect(r.record_type).toBe('order')
    }
  })

  it('三个订单级分组字段都与 _g 一致（三列各自拿它做跨行合并）', () => {
    // 组件把「时间/编号/客户」三列的 field 分别指到这三个字段上
    // （三列不能共用一个 field：UiDataTable 的插槽名是 column-body-${field}，同名就分不开了）
    const rows = flattenRecordRows([ORDER_3SKU])

    expect(rows.length).toBe(3)
    const key = rows[0]!._g
    for (const r of rows) {
      expect(r._g_date).toBe(key)
      expect(r._g_no).toBe(key)
      expect(r._g_cust).toBe(key)
    }
  })

  it('单 SKU 订单只摊 1 行', () => {
    const rows = flattenRecordRows([ORDER_1SKU])

    expect(rows.length).toBe(1)
    expect(rows[0]!.product_name).toBe('测试')
    expect(rows[0]!.quantity).toBe(10000)
  })

  it('备货行同样只摊 1 行，且记录类型仍是 stockin', () => {
    const rows = flattenRecordRows([STOCKIN])

    expect(rows.length).toBe(1)
    expect(rows[0]!.record_type).toBe('stockin')
    expect(rows[0]!.product_name).toBe('鲨鱼')
  })

  it('行键全局唯一（PrimeVue row-key 要求；不同订单的 SKU id 可能撞号）', () => {
    // 订单与备货来自不同表，id 各自从 1 开始，撞号是常态
    const clash = { ...ORDER_1SKU, id: 39268, items: [{ id: 39268, product_name: '撞号 SKU', quantity: 5 }] } as OrderRecord
    const rows = flattenRecordRows([STOCKIN, clash])

    expect(rows.length, '先锁行数，避免空数组让唯一性断言真空通过').toBe(2)
    const keys = rows.map((r) => r._rowKey)
    expect(new Set(keys).size, '行键必须唯一').toBe(keys.length)
  })

  it('两个 id 相同但来源不同的行，行键仍不同（订单 39268 vs 备货 39268）', () => {
    const clash = { ...ORDER_1SKU, id: 39268, items: [{ id: 39268, product_name: '撞号 SKU', quantity: 5 }] } as OrderRecord
    const rows = flattenRecordRows([STOCKIN, clash])

    const stockinRow = rows.find((r) => r.record_type === 'stockin')!
    const orderRow = rows.find((r) => r.record_type === 'order')!
    expect(stockinRow._rowKey).not.toBe(orderRow._rowKey)
  })

  it('items 缺失时按订单自身回退为 1 行（不产出空行）', () => {
    const noItems = { ...ORDER_1SKU, items: undefined, product: { id: 1, name: '回退产品名' } } as unknown as OrderRecord
    const rows = flattenRecordRows([noItems])

    expect(rows.length).toBe(1)
    expect(rows[0]!.product_name).toBe('回退产品名')
    expect(rows[0]!.quantity).toBe(10000)
  })

  it('空列表摊平为空', () => {
    expect(flattenRecordRows([])).toEqual([])
  })
})
