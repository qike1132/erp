/**
 * shipCartModel 纯函数单测
 *
 * 覆盖批量发货的核心业务规则：聚合（挑选项/清单行）、数量拆分（按订单顺序）、
 * 校验口径（整数/上限）、实时剩余。这些规则原先内联在组件里，拆出后在此直接验证。
 */
import { describe, it, expect } from 'vitest'
import {
  mergeKey, productRows, buildOrderOptions, buildPickGroups,
  buildCartGroups, splitQty, rowQty, isRowInvalid,
  type CartProcessRow, type MergedInput,
} from '@/views/outsource/components/shipCartModel'
import type { ShippableProcessItem } from '@/api/outsource'

function row(over: Partial<ShippableProcessItem> = {}): ShippableProcessItem {
  const remaining = over.remaining ?? 100
  return {
    process_id: 1, order_id: 1, order_no: 'PO-A', customer: '客户A',
    product_name: 'SKU-A', process_type: '电绣',
    target_qty: (over.target_qty ?? remaining) + (over.shipped_qty ?? 0),
    shipped_qty: 0, remaining,
    ...over,
  }
}

function procRow(over: {
  qty?: number; on?: boolean; remaining?: number; entries?: ShippableProcessItem[]
} = {}): CartProcessRow {
  const input: MergedInput = { qty: over.qty ?? 0, on: over.on ?? true }
  return {
    key: 'K', processType: '电绣',
    entries: over.entries ?? [row()],
    targetQty: 0, remaining: over.remaining ?? 100,
    input,
  }
}

describe('mergeKey / productRows', () => {
  it('合并键为 产品名||工序名', () => {
    expect(mergeKey('SKU-A', '电绣')).toBe('SKU-A||电绣')
  })

  it('productRows 按产品名过滤，空名回退「未命名产品」', () => {
    const rows = [row(), row({ process_id: 2, product_name: null })]
    expect(productRows(rows, 'SKU-A').length).toBe(1)
    expect(productRows(rows, '未命名产品').length).toBe(1)
  })
})

describe('buildOrderOptions', () => {
  it('按 order_id 去重，保留首次出现顺序', () => {
    const opts = buildOrderOptions([row(), row({ process_id: 2 }), row({ process_id: 3, order_id: 2, order_no: 'PO-B' })])
    expect(opts).toEqual([
      { order_id: 1, order_no: 'PO-A', customer: '客户A' },
      { order_id: 2, order_no: 'PO-B', customer: '客户A' },
    ])
  })
})

describe('buildPickGroups', () => {
  it('同一产品跨订单合并为一组，orderCount 正确；不同产品各自成组', () => {
    const groups = buildPickGroups([
      row({ process_id: 1, process_type: '电绣' }),
      row({ process_id: 2, order_id: 2, order_no: 'PO-B', process_type: '转印' }),
      row({ process_id: 3, order_id: 3, order_no: 'PO-C', product_name: 'SKU-B', process_type: '电绣' }),
    ])
    expect(groups.length).toBe(2)
    const a = groups.find((g) => g.productName === 'SKU-A')!
    expect(a.orderIds).toEqual([1, 2])
    expect(a.orderCount).toBe(2)
  })

  it('按产品名排序输出', () => {
    const groups = buildPickGroups([row({ product_name: 'B品' }), row({ process_id: 2, product_name: 'A品' })])
    expect(groups.map((g) => g.productName)).toEqual(['A品', 'B品'])
  })
})

describe('buildCartGroups', () => {
  it('同产品同工序跨订单合并为一行，targetQty/remaining 为合计', () => {
    const inputs = new Map()
    const groups = buildCartGroups(
      [row({ remaining: 100 }), row({ process_id: 2, order_id: 2, remaining: 200 })],
      ['SKU-A'], inputs,
    )
    expect(groups.length).toBe(1)
    expect(groups[0]!.processes.length).toBe(1)
    expect(groups[0]!.processes[0]!.remaining).toBe(300)
    expect(groups[0]!.processes[0]!.targetQty).toBe(300)
  })

  it('缺失键写入默认值 { qty: 剩余合计, on: true }；已有键不覆盖用户已填值', () => {
    const inputs = new Map()
    buildCartGroups([row({ remaining: 100 })], ['SKU-A'], inputs)
    expect(inputs.get('SKU-A||电绣')).toEqual({ qty: 100, on: true })

    inputs.set('SKU-A||电绣', { qty: 30, on: false })
    buildCartGroups([row({ remaining: 100 })], ['SKU-A'], inputs)
    expect(inputs.get('SKU-A||电绣')).toEqual({ qty: 30, on: false })
  })

  it('只输出 cartProducts 中的产品，保持加入顺序', () => {
    const inputs = new Map()
    const groups = buildCartGroups(
      [row(), row({ process_id: 2, product_name: 'SKU-B' })],
      ['SKU-B', 'SKU-A'], inputs,
    )
    expect(groups.map((g) => g.productName)).toEqual(['SKU-B', 'SKU-A'])
  })
})

describe('splitQty', () => {
  it('按订单顺序依次填满剩余量，0 数量订单不返回', () => {
    const entries = [row({ process_id: 1, remaining: 100 }), row({ process_id: 2, order_id: 2, remaining: 200 })]
    const r = procRow({ qty: 250, entries, remaining: 300 })
    expect(splitQty(r)).toEqual([
      { row: entries[0], quantity: 100 },
      { row: entries[1], quantity: 150 },
    ])
  })

  it('数量为 0 / 负数 / NaN 返回空数组', () => {
    expect(splitQty(procRow({ qty: 0 }))).toEqual([])
    expect(splitQty(procRow({ qty: -5 }))).toEqual([])
    expect(splitQty(procRow({ qty: NaN }))).toEqual([])
  })
})

describe('isRowInvalid / rowQty', () => {
  it('未勾选恒不非法，且不计入合计', () => {
    const r = procRow({ qty: 99999, on: false })
    expect(isRowInvalid(r)).toBe(false)
    expect(rowQty(r)).toBe(0)
  })

  it('小数 / 0 / 负数 / 超上限为非法', () => {
    expect(isRowInvalid(procRow({ qty: 1.5 }))).toBe(true)
    expect(isRowInvalid(procRow({ qty: 0 }))).toBe(true)
    expect(isRowInvalid(procRow({ qty: -1 }))).toBe(true)
    expect(isRowInvalid(procRow({ qty: 101 }))).toBe(true)
  })

  it('1 到上限的整数合法并计入合计', () => {
    expect(isRowInvalid(procRow({ qty: 1 }))).toBe(false)
    expect(isRowInvalid(procRow({ qty: 100 }))).toBe(false)
    expect(rowQty(procRow({ qty: 60 }))).toBe(60)
  })
})
