import { describe, expect, it } from 'vitest'

import { buildRecordsQuery, buildExportRange, defaultRecordFilters } from '@/views/production/composables/recordFilters'

// 固定"今天"为周三，便于断言"本周"
const WED = new Date(2026, 8, 30) // 2026-09-30

function filters(overrides: Partial<ReturnType<typeof defaultRecordFilters>> = {}) {
  return { ...defaultRecordFilters(), ...overrides }
}

describe('buildRecordsQuery', () => {
  it('本月：只传 year/month，不传区间', () => {
    const q = buildRecordsQuery(filters({ preset: 'month' }), WED)

    expect(q).toEqual({ year: 2026, month: 9, page: 1, per_page: 50, sort: 'desc' })
  })

  it('今日：传当月 year/month 加 production_date 单日', () => {
    const q = buildRecordsQuery(filters({ preset: 'today' }), WED)

    expect(q).toEqual({ year: 2026, month: 9, production_date: '2026-09-30', page: 1, per_page: 50, sort: 'desc' })
  })

  it('本周：从本周一到今天，走区间且不带 year/month', () => {
    // Review Focus #5：本周可能跨月
    const q = buildRecordsQuery(filters({ preset: 'week' }), WED)

    expect(q).toEqual({ start_date: '2026-09-28', end_date: '2026-09-30', page: 1, per_page: 50, sort: 'desc' })
  })

  it('自定义：区间原样透传，不带 year/month', () => {
    const q = buildRecordsQuery(
      filters({ preset: 'custom', customStart: '2026-08-25', customEnd: '2026-09-02' }),
      WED,
    )

    expect(q.start_date).toBe('2026-08-25')
    expect(q.end_date).toBe('2026-09-02')
    expect(q).not.toHaveProperty('year')
  })

  it('自定义区间只填了一半时回退到本月，不发出半个区间', () => {
    const q = buildRecordsQuery(filters({ preset: 'custom', customStart: '2026-08-25', customEnd: '' }), WED)

    expect(q).toEqual({ year: 2026, month: 9, page: 1, per_page: 50, sort: 'desc' })
  })

  it('自定义区间反向时回退到本月', () => {
    const q = buildRecordsQuery(
      filters({ preset: 'custom', customStart: '2026-09-10', customEnd: '2026-09-01' }),
      WED,
    )

    expect(q).toEqual({ year: 2026, month: 9, page: 1, per_page: 50, sort: 'desc' })
  })

  it('空部门不传 department 键', () => {
    const q = buildRecordsQuery(filters({ department: '' }), WED)

    expect(q).not.toHaveProperty('department')
  })

  it('指定部门时传 department', () => {
    const q = buildRecordsQuery(filters({ department: 'filling' }), WED)

    expect(q.department).toBe('filling')
  })

  it('录单人留空时不传 created_by 键（绝不能传空串）', () => {
    // Review Focus #5：传 created_by='' 会被后端当成"只看录单人为空的记录"
    const q = buildRecordsQuery(filters({ createdBy: '   ' }), WED)

    expect(q).not.toHaveProperty('created_by')
  })

  it('录单人有值时去掉首尾空格再传', () => {
    const q = buildRecordsQuery(filters({ createdBy: ' 张三 ' }), WED)

    expect(q.created_by).toBe('张三')
  })

  it('关键词留空时不传 keyword 键', () => {
    const q = buildRecordsQuery(filters({ keyword: '  ' }), WED)

    expect(q).not.toHaveProperty('keyword')
  })

  it('关键词有值时去掉首尾空格再传', () => {
    const q = buildRecordsQuery(filters({ keyword: ' 白兔 ' }), WED)

    expect(q.keyword).toBe('白兔')
  })

  it('页码与每页条数原样带上', () => {
    const q = buildRecordsQuery(filters({ page: 3, perPage: 100 }), WED)

    expect(q.page).toBe(3)
    expect(q.per_page).toBe(100)
  })
})

/**
 * 审计 #1：抽屉查询/抽屉导出的日期基准必须是**页面选中日期**，不是「今天」。
 *
 * 拦的错：报表页按 selectedDate 取日报，抽屉却按当前自然月查 —— 点 12 月某天的
 * 部门卡，抽屉里看到的是本月数据；抽屉导出的区间同样偏到本月。
 * 这里传入 'YYYY-MM-DD' 字符串（与页面 selectedDate 同形），断言年月跟着走。
 */
describe('日期基准（审计 #1）', () => {
  const SELECTED = '2025-12-15'

  it('选中日期的月份决定抽屉查询的 year/month', () => {
    const q = buildRecordsQuery(filters({ preset: 'month' }), SELECTED)

    expect(q.year).toBe(2025)
    expect(q.month).toBe(12)
    expect(q).not.toHaveProperty('start_date')
  })

  it('「今日」预设取的是选中日期当天，而不是今天', () => {
    const q = buildRecordsQuery(filters({ preset: 'today' }), SELECTED)

    expect(q.production_date).toBe('2025-12-15')
    expect(q.year).toBe(2025)
    expect(q.month).toBe(12)
  })

  it('「本周」预设从选中日期所在周的周一起算（不跨到当前周）', () => {
    const q = buildRecordsQuery(filters({ preset: 'week' }), SELECTED)

    expect(q.start_date).toBe('2025-12-15') // 2025-12-15 是周一
    expect(q.end_date).toBe('2025-12-15')
  })

  it('导出区间按选中日期所在月折算，而不是当前自然月', () => {
    expect(buildExportRange(filters({ preset: 'month' }), SELECTED)).toEqual({
      start_date: '2025-12-01',
      end_date: '2025-12-31',
    })
  })

  it('非法日期串退回「今天」，不会把 NaT 传出去', () => {
    // 兼容性护栏：调用方万一传了空串/坏串，行为必须等价于既有的默认参数
    const q = buildRecordsQuery(filters({ preset: 'month' }), '')

    expect(typeof q.year).toBe('number')
    expect(typeof q.month).toBe('number')
  })

  it('不传第二参数时沿用既有默认值（其他调用方兼容）', () => {
    const q = buildRecordsQuery(filters({ preset: 'month' }))

    // 手写断言：默认就是「今天」所在月，不能退化成固定值或 undefined
    const now = new Date()
    expect(q.year).toBe(now.getFullYear())
    expect(q.month).toBe(now.getMonth() + 1)
  })
})

describe('buildExportRange', () => {
  // 导出接口只吃 start_date/end_date（没有 year/month），所以每个预设都要折算成闭区间。
  it('今日：区间收成同一天', () => {
    expect(buildExportRange(filters({ preset: 'today' }), WED)).toEqual({
      start_date: '2026-09-30',
      end_date: '2026-09-30',
    })
  })

  it('本周：从本周一到今天', () => {
    expect(buildExportRange(filters({ preset: 'week' }), WED)).toEqual({
      start_date: '2026-09-28',
      end_date: '2026-09-30',
    })
  })

  it('本月：首日到末日（30 天月）', () => {
    expect(buildExportRange(filters({ preset: 'month' }), WED)).toEqual({
      start_date: '2026-09-01',
      end_date: '2026-09-30',
    })
  })

  it('本月：二月（非闰年）末日照实算到 28', () => {
    expect(buildExportRange(filters({ preset: 'month' }), new Date(2026, 1, 15))).toEqual({
      start_date: '2026-02-01',
      end_date: '2026-02-28',
    })
  })

  it('本月：闰年二月末日照实算到 29', () => {
    expect(buildExportRange(filters({ preset: 'month' }), new Date(2024, 1, 10))).toEqual({
      start_date: '2024-02-01',
      end_date: '2024-02-29',
    })
  })

  it('自定义：两端原样透传', () => {
    expect(
      buildExportRange(filters({ preset: 'custom', customStart: '2026-08-25', customEnd: '2026-09-02' }), WED),
    ).toEqual({ start_date: '2026-08-25', end_date: '2026-09-02' })
  })

  it('自定义区间只填一半时回退到本月（与列表查询同规则）', () => {
    expect(
      buildExportRange(filters({ preset: 'custom', customStart: '2026-08-25', customEnd: '' }), WED),
    ).toEqual({ start_date: '2026-09-01', end_date: '2026-09-30' })
  })

  it('自定义区间反向时回退到本月', () => {
    expect(
      buildExportRange(filters({ preset: 'custom', customStart: '2026-09-10', customEnd: '2026-09-01' }), WED),
    ).toEqual({ start_date: '2026-09-01', end_date: '2026-09-30' })
  })
})
