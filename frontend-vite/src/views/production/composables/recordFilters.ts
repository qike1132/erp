/**
 * 明细抽屉的筛选状态 → 请求参数。
 *
 * 抽成纯函数的原因：这里有一批容易写错、且错了不容易看出来的边界 ——
 * 本周可能跨月（必须走区间）、自定义区间只填一半或填反（必须回退而不是发出去）、
 * 录单人/关键词留空（必须省略键而不是传空串 —— 后端会把空串当成"等于空"）。
 */
import type { RecordsQuery } from '@/types'
import { mondayOf, toLocalDate } from './productionDate'

export type RangePreset = 'today' | 'week' | 'month' | 'custom'

export interface RecordFilters {
  preset: RangePreset
  customStart: string
  customEnd: string
  department: string
  createdBy: string
  keyword: string
  page: number
  perPage: number
}

export function defaultRecordFilters(): RecordFilters {
  return {
    preset: 'month',
    customStart: '',
    customEnd: '',
    department: '',
    createdBy: '',
    keyword: '',
    page: 1,
    perPage: 50,
  }
}

function isReversed(start: string, end: string): boolean {
  return !!start && !!end && end < start
}

export function buildRecordsQuery(filters: RecordFilters, today: Date = new Date()): RecordsQuery {
  const query: RecordsQuery = {
    page: filters.page,
    per_page: filters.perPage,
    sort: 'desc',
  }

  const y = today.getFullYear()
  const m = today.getMonth() + 1

  if (filters.preset === 'custom' && filters.customStart && filters.customEnd && !isReversed(filters.customStart, filters.customEnd)) {
    query.start_date = filters.customStart
    query.end_date = filters.customEnd
  } else if (filters.preset === 'week') {
    query.start_date = toLocalDate(mondayOf(today))
    query.end_date = toLocalDate(today)
  } else if (filters.preset === 'today') {
    query.year = y
    query.month = m
    query.production_date = toLocalDate(today)
  } else {
    // 'month'，以及自定义区间填了一半/填反时的回退
    query.year = y
    query.month = m
  }

  if (filters.department) query.department = filters.department
  if (filters.createdBy.trim()) query.created_by = filters.createdBy.trim()
  if (filters.keyword.trim()) query.keyword = filters.keyword.trim()

  return query
}

/**
 * 导出用的日期区间：把当前筛选的区间预设折算成一对闭区间端点。
 *
 * 与 `buildRecordsQuery` 的差别：导出接口只接受 start_date/end_date（没有 year/month），
 * 所以「本月」必须折算成该月首日…末日；自定义区间填了一半/填反时同样回退到本月，
 * 与列表查询的回退规则保持一致 —— 否则"看到的是本月、导出的是别的区间"。
 */
export function buildExportRange(filters: RecordFilters, today: Date = new Date()): { start_date: string; end_date: string } {
  if (filters.preset === 'custom' && filters.customStart && filters.customEnd && !isReversed(filters.customStart, filters.customEnd)) {
    return { start_date: filters.customStart, end_date: filters.customEnd }
  }
  if (filters.preset === 'week') {
    return { start_date: toLocalDate(mondayOf(today)), end_date: toLocalDate(today) }
  }
  if (filters.preset === 'today') {
    const day = toLocalDate(today)
    return { start_date: day, end_date: day }
  }
  // 'month'，以及自定义区间填了一半/填反时的回退
  const first = new Date(today.getFullYear(), today.getMonth(), 1)
  const last = new Date(today.getFullYear(), today.getMonth() + 1, 0)
  return { start_date: toLocalDate(first), end_date: toLocalDate(last) }
}
