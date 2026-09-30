/**
 * 记录列表的行摊平（多 SKU 分行的数据准备）—— 纯函数，先于实现写。
 *
 * 背景：一张订单可含多个 SKU，而 `GET /orders/records` 一行一个订单（items[] 里挂 SKU）。
 * 要把「每个 SKU 的产品名称与数量各自落在产品名称列/数量列」，必须摊平成一行一 SKU。
 *
 * 摊平后每条订单产出 N 行 SKU + （多 SKU 时）1 行合计：
 * - 订单级字段（时间/编号/客户）在每行都带上真值，供组件渲染；
 * - `_g` 是同订单恒等的**分组键**，供表格做跨行合并；合计行的 `_g` 另取一值（自己成组），
 *   这样合并不会把合计行也并进去；
 * - `_rowKey` 全局唯一（PrimeVue 的 row-key 要求），故含 SKU 序号。
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
  it('3 个 SKU 的订单摊成 3 行 SKU + 1 行合计，每行数量取该 SKU 自己的数量', () => {
    const rows = flattenRecordRows([ORDER_3SKU])

    expect(rows.length).toBe(4)
    expect(rows.slice(0, 3).map((r) => r.product_name)).toEqual([
      '《蛋仔派对》市集拾趣系列 毛绒公仔挂件盲盒',
      '鲨鱼',
      '《蛋仔派对》团子木鱼毛绒挂件盲盒-黄蛋 陈列样',
    ])
    expect(rows.slice(0, 3).map((r) => r.quantity)).toEqual([10000, 10000, 10000])
    expect(rows.slice(0, 3).map((r) => r._isSum)).toEqual([false, false, false])
    // 合计行落在数量列上，值等于订单总量
    expect(rows[3]!._isSum).toBe(true)
    expect(rows[3]!.quantity).toBe(30000)
  })

  it('同一订单的 SKU 行共享同一个分组键（跨行合并的前提）', () => {
    const rows = flattenRecordRows([ORDER_3SKU])

    const skuKeys = rows.slice(0, 3).map((r) => r._g)
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

    expect(rows.length, '先锁行数，避免空数组让下面的循环真空通过').toBe(4)
    for (const r of rows.slice(0, 3)) {
      expect(r.order_date).toBe('2026-09-30 00:00')
      expect(r.order_no).toBe('PO-20260930-0013')
      expect(r.customer).toBe('MINISO国际')
      expect(r.record_type).toBe('order')
    }
  })

  it('单 SKU 订单只摊 1 行，且不产生合计行（那一行本身就是总量）', () => {
    const rows = flattenRecordRows([ORDER_1SKU])

    expect(rows.length).toBe(1)
    expect(rows[0]!.product_name).toBe('测试')
    expect(rows[0]!.quantity).toBe(10000)
    expect(rows[0]!._isSum).toBe(false)
  })

  it('备货行同样只摊 1 行，且不带操作入口所需的订单删除语义', () => {
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

  it('合计行与 SKU 行共用分组键 —— 合并格必须一直盖到合计行', () => {
    // 组件把「时间/编号/客户」三列的 field 分别指到这三个字段上做跨行合并
    // （三列不能共用一个 field：UiDataTable 的插槽名是 column-body-${field}，同名就分不开了）。
    //
    // 合计行**共用**分组键是刻意的：这样它的上面三格被 SKU 行的跨行格盖住，
    // 合并数 = SKU 数 + 1，视觉上「合计」落在这张订单的块里（与已确认的对比稿一致）。
    // 若让合计行自成分组，合并格会停在合计行上方，合计行左侧出现三个空白格。
    const rows = flattenRecordRows([ORDER_3SKU])

    expect(rows.length).toBe(4)
    const skuKey = rows[0]!._g
    for (const r of rows.slice(0, 3)) {
      expect(r._g_date).toBe(skuKey)
      expect(r._g_no).toBe(skuKey)
      expect(r._g_cust).toBe(skuKey)
    }

    const sum = rows[3]!
    expect(sum._isSum).toBe(true)
    expect(sum._g, '合计行必须与 SKU 行同组，否则合并格盖不到它').toBe(skuKey)
    for (const field of ['_g_date', '_g_no', '_g_cust'] as const) {
      expect(sum[field], `${field} 必须与 SKU 行同值，否则合并格盖不到合计行`).toBe(skuKey)
    }
    // 行键仍要唯一：合计行不能与任何 SKU 行撞键
    expect(sum._rowKey).not.toBe(rows[0]!._rowKey)
  })

  it('空列表摊平为空', () => {
    expect(flattenRecordRows([])).toEqual([])
  })
})
