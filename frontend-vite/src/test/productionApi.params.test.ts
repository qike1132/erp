import { describe, expect, it, vi, beforeEach } from 'vitest'

const getMock = vi.fn()

vi.mock('@/api/request', () => ({
  get: (...args: unknown[]) => getMock(...args),
  post: vi.fn(),
  put: vi.fn(),
  del: vi.fn(),
  download: vi.fn(),
}))

import { dailyProductionApi } from '@/api/production'

describe('dailyProductionApi.records', () => {
  beforeEach(() => {
    getMock.mockReset()
    getMock.mockResolvedValue({ success: true, data: [], total: 0, page: 1, per_page: 50, pages: 0, stats: null })
  })

  it('按年月筛选时只传 year/month', async () => {
    await dailyProductionApi.records({ year: 2026, month: 9, page: 1, per_page: 50 })

    expect(getMock).toHaveBeenCalledWith('/daily-production/records', {
      year: 2026,
      month: 9,
      page: 1,
      per_page: 50,
    })
  })

  it('按区间筛选时传 start_date/end_date 且不带 year/month', async () => {
    await dailyProductionApi.records({ start_date: '2026-08-25', end_date: '2026-09-02' })

    const params = getMock.mock.calls[0]![1] as Record<string, unknown>
    expect(params).toEqual({ start_date: '2026-08-25', end_date: '2026-09-02' })
    expect(params).not.toHaveProperty('year')
    expect(params).not.toHaveProperty('month')
  })

  it('参数原样透传，不在 API 层补默认值', async () => {
    // 默认值由调用方（useProductionRecords）决定；API 层补默认值会让"区间"筛选被
    // 悄悄带上 year/month，后端虽有"区间优先"规则，但前端不该依赖它兜底。
    await dailyProductionApi.records({ created_by: '张三' })

    expect(getMock).toHaveBeenCalledWith('/daily-production/records', { created_by: '张三' })
  })
})

describe('dailyProductionApi.trend', () => {
  beforeEach(() => {
    getMock.mockReset()
    getMock.mockResolvedValue({
      success: true, start_date: '2026-09-01', end_date: '2026-09-02',
      departments: ['filling', 'handcraft', 'packaging'], days: [],
    })
  })

  it('传区间与可选部门', async () => {
    await dailyProductionApi.trend({ start_date: '2026-09-01', end_date: '2026-09-30', department: 'filling' })

    expect(getMock).toHaveBeenCalledWith('/daily-production/trend', {
      start_date: '2026-09-01',
      end_date: '2026-09-30',
      department: 'filling',
    })
  })

  it('不传部门时参数里没有 department 键', async () => {
    await dailyProductionApi.trend({ start_date: '2026-09-01', end_date: '2026-09-30' })

    expect(getMock.mock.calls[0]![1]).toEqual({ start_date: '2026-09-01', end_date: '2026-09-30' })
  })
})
