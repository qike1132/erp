/**
 * 「来源订单」逐单展示数量分配（2026-11-09 用户反馈）。
 *
 * 主行「数量」是损耗加放后向上取整的采购量（与工厂内部订单同源）。
 * 来源明细必须显示整数且相加等于主行数量，不能直接露出后端原始小数（如 8.33）。
 */
import { describe, it, expect } from 'vitest'
import { allocateOrderDisplayQuantities } from '@/views/purchase/composables/perSkuRows'

describe('allocateOrderDisplayQuantities', () => {
  it('单一张单：8.33 按主行 9 展示为整数', () => {
    const lines = allocateOrderDisplayQuantities(9, [
      { order_no: 'PO-2611-003', quantity: 8.33 },
    ])

    expect(lines).toEqual([{ order_no: 'PO-2611-003', quantity: 9 }])
  })

  it('多单按原始量占比分配，合计严格等于主行', () => {
    const lines = allocateOrderDisplayQuantities(120, [
      { order_no: 'PO-001', quantity: 30 },
      { order_no: 'PO-002', quantity: 50 },
      { order_no: 'PO-003', quantity: 40 },
    ])

    expect(lines.map((l) => l.quantity)).toEqual([30, 50, 40])
    expect(lines.reduce((s, l) => s + l.quantity, 0)).toBe(120)
  })

  it('无法整除时用最大余数法，仍保证合计一致且全为整数', () => {
    const lines = allocateOrderDisplayQuantities(10, [
      { order_no: 'PO-001', quantity: 1 },
      { order_no: 'PO-002', quantity: 1 },
      { order_no: 'PO-003', quantity: 1 },
    ])

    expect(lines.map((l) => l.quantity)).toEqual([4, 3, 3])
    expect(lines.reduce((s, l) => s + l.quantity, 0)).toBe(10)
  })

  it('原始量全为 0 时平均分配，合计不变', () => {
    const lines = allocateOrderDisplayQuantities(5, [
      { order_no: 'PO-001', quantity: 0 },
      { order_no: 'PO-002', quantity: 0 },
    ])

    expect(lines.map((l) => l.quantity)).toEqual([3, 2])
  })

  it('主行带小数（BOM 回退异常行）时按 0.01 分配，仍与主行相等', () => {
    const lines = allocateOrderDisplayQuantities(20.1, [
      { order_no: 'PO-001', quantity: 10 },
      { order_no: 'PO-002', quantity: 10 },
    ])

    expect(lines.map((l) => l.quantity)).toEqual([10.05, 10.05])
    expect(lines.reduce((s, l) => s + l.quantity, 0)).toBeCloseTo(20.1, 10)
  })

  it('无来源订单返回空数组', () => {
    expect(allocateOrderDisplayQuantities(9, [])).toEqual([])
  })
})
