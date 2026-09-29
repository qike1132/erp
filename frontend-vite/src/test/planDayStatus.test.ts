import { describe, it, expect } from 'vitest'
import {
  dayMarkFor,
  daysFromToday,
  startOfToday,
  todayIso,
} from '../views/purchase-plan/components/dayStatus'

// 固定「今天」为 2026-09-28 15:30 —— 刻意取下午，验证零点对齐：
// 若实现直接用 now 比对，当天会被算成已过期的负差。
const TODAY = startOfToday(new Date('2026-09-28T15:30:00'))

const row = (date: string, shippedPct: number, pendingCount: number) => ({
  date,
  _shippedPct: shippedPct,
  _pendingCount: pendingCount,
})

describe('daysFromToday 按本地零点对齐', () => {
  it('当天为 0，即使已经过了正午', () => {
    expect(daysFromToday('2026-09-28', TODAY)).toBe(0)
  })

  it('过去为负、未来为正', () => {
    expect(daysFromToday('2026-09-08', TODAY)).toBe(-20)
    expect(daysFromToday('2026-09-30', TODAY)).toBe(2)
  })
})

describe('startOfToday / todayIso', () => {
  it('抹掉时分秒', () => {
    expect(new Date(startOfToday(new Date('2026-09-28T15:30:45'))).getHours()).toBe(0)
  })

  it('todayIso 补零', () => {
    expect(todayIso(new Date('2026-09-08T09:00:00'))).toBe('2026-09-08')
  })
})

describe('dayMarkFor 的判定优先级', () => {
  it('全部出货优先于一切 —— 已过期的日子也算完成，不算延期', () => {
    expect(dayMarkFor(row('2026-09-08', 100, 3), TODAY)).toEqual({ cls: 'st-g', lbl: '✓ 完成' })
  })

  it('无待出条数 → 不打标记，即使没到 100%', () => {
    expect(dayMarkFor(row('2026-09-08', 0, 0), TODAY)).toBeNull()
  })

  it('过期 → 延期 N 天', () => {
    expect(dayMarkFor(row('2026-09-08', 64, 3), TODAY)).toEqual({ cls: 'st-r', lbl: '延期 20天' })
  })

  it('当天 → 今日出货', () => {
    expect(dayMarkFor(row('2026-09-28', 0, 1), TODAY)).toEqual({ cls: 'st-r', lbl: '今日出货' })
  })

  it('1~3 天 → 临期 N 天', () => {
    expect(dayMarkFor(row('2026-09-29', 0, 2), TODAY)).toEqual({ cls: 'st-a', lbl: '临期 1天' })
    expect(dayMarkFor(row('2026-10-01', 0, 2), TODAY)).toEqual({ cls: 'st-a', lbl: '临期 3天' })
  })

  it('第 4 天及以后 → 不标记', () => {
    expect(dayMarkFor(row('2026-10-02', 0, 2), TODAY)).toBeNull()
  })
})
