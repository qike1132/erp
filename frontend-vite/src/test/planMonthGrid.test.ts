import { describe, it, expect } from 'vitest'
import {
  buildMonthCells,
  type MonthCell,
} from '../views/purchase-plan/components/dayStatus'

/** 开了 noUncheckedIndexedAccess，下标访问一律走这里，避免每行都写 ! */
function at<T>(cells: MonthCell<T>[], i: number): MonthCell<T> {
  const c = cells[i]
  if (!c) throw new Error(`下标 ${i} 越界（共 ${cells.length} 格）`)
  return c
}

function dayCell<T>(cells: MonthCell<T>[], day: number): MonthCell<T> {
  const c = cells.find(x => x.day === day)
  if (!c) throw new Error(`格子 ${day} 不存在`)
  return c
}

const allBlank = <T>(cells: MonthCell<T>[]) => cells.every(c => c.day === null)

type QtyRow = { date: string; totalQty: number }

describe('buildMonthCells —— 周一起始的月历铺格', () => {
  it('2026-09：1 号是周二 → 首行补 1 格，5 行 35 格', () => {
    const cells = buildMonthCells(2026, 9, [] as QtyRow[])
    expect(cells).toHaveLength(35)
    expect(at(cells, 0).day).toBeNull()
    expect(at(cells, 1).day).toBe(1)
    expect(dayCell(cells, 30).day).toBe(30)
    expect(allBlank(cells.slice(31))).toBe(true)
  })

  it('2026-10：1 号是周四 → 首行补 3 格', () => {
    const cells = buildMonthCells(2026, 10, [] as QtyRow[])
    expect(cells).toHaveLength(35)
    expect(allBlank(cells.slice(0, 3))).toBe(true)
    expect(at(cells, 3).day).toBe(1)
    expect(at(cells, 3).date).toBe('2026-10-01')
  })

  it('2026-08：1 号是周六 → 首行补 5 格，31 天要 6 行 42 格', () => {
    const cells = buildMonthCells(2026, 8, [] as QtyRow[])
    expect(cells).toHaveLength(42)
    expect(at(cells, 5).day).toBe(1)
    expect(dayCell(cells, 31).date).toBe('2026-08-31')
    expect(allBlank(cells.slice(36))).toBe(true)
  })

  it('2026-02（非闰年）：28 天 + 1 号是周日 → 补 6 格，不出现 29 号', () => {
    const cells = buildMonthCells(2026, 2, [] as QtyRow[])
    expect(cells).toHaveLength(35)
    expect(at(cells, 6).day).toBe(1)
    expect(dayCell(cells, 28).date).toBe('2026-02-28')
    expect(cells.some(c => c.date === '2026-02-29')).toBe(false)
  })

  it('2024-02（闰年）：29 天', () => {
    const cells = buildMonthCells(2024, 2, [] as QtyRow[])
    expect(cells).toHaveLength(35)
    expect(dayCell(cells, 29).date).toBe('2024-02-29')
  })

  it('日号补零成 ISO 日期串', () => {
    const cells = buildMonthCells(2026, 9, [] as QtyRow[])
    expect(dayCell(cells, 8).date).toBe('2026-09-08')
  })

  it('有排产的日期挂到对应格子，其余 row 为 null', () => {
    const rows: QtyRow[] = [
      { date: '2026-09-08', totalQty: 5000 },
      { date: '2026-09-29', totalQty: 2200 },
    ]
    const cells = buildMonthCells(2026, 9, rows)
    expect(dayCell(cells, 8).row?.totalQty).toBe(5000)
    expect(dayCell(cells, 29).row?.totalQty).toBe(2200)
    expect(dayCell(cells, 9).row).toBeNull()
  })

  it('同一天重复行取首行，不被末行静默覆盖', () => {
    const rows: QtyRow[] = [
      { date: '2026-09-08', totalQty: 1 },
      { date: '2026-09-08', totalQty: 2 },
    ]
    const cells = buildMonthCells(2026, 9, rows)
    expect(dayCell(cells, 8).row?.totalQty).toBe(1)
  })

  it('月份外的日期不会漏进格子', () => {
    const rows: QtyRow[] = [{ date: '2026-08-31', totalQty: 9 }]
    const cells = buildMonthCells(2026, 9, rows)
    expect(cells.some(c => c.row !== null)).toBe(false)
  })

  it('格子 key 唯一（空格子不能撞 key）', () => {
    const cells = buildMonthCells(2026, 9, [] as QtyRow[])
    expect(new Set(cells.map(c => c.key)).size).toBe(cells.length)
  })
})
