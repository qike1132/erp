import { describe, expect, it } from 'vitest'

import { buildRecordsQuery, defaultRecordFilters } from '@/views/production/composables/recordFilters'

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

    expect(q.start_date).toBe('2026-09-28')
    expect(q.end_date).toBe('2026-09-30')
    expect(q).not.toHaveProperty('year')
    expect(q).not.toHaveProperty('month')
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

    expect(q).not.toHaveProperty('start_date')
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
