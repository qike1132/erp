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

/**
 * 日期基准：`Date`（既有调用方）或页面选中日期 `'YYYY-MM-DD'`。
 *
 * 为什么允许字符串：抽屉的「本月/本周/今日」必须锚在**页面选中的那一天**，
 * 而不是锚在「今天」—— 用户在 12 月的日报页点某个部门卡，抽屉却查当前自然月，
 * 看到的就是本月数据（2026-11-16 上线前审计 #1）。页面上的日期本身就是
 * 'YYYY-MM-DD' 字符串，直接传进来不必在调用点反复 new Date。
 */
export type DateBase = Date | string

/**
 * 字符串按**本地时区**解析（`'...T00:00:00'` + Date 构造而非 `new Date(str)`）：
 * ISO 纯日期串会被 `new Date()` 按 UTC 解析，东八区整体偏移一天（月末/月初最明显）。
 */
function resolveBaseDate(base: DateBase): Date {
  if (base instanceof Date) return base
  const parsed = new Date(`${base}T00:00:00`)
  // 非法字符串退回「今天」，与既有默认参数保持同一兜底语义
  return Number.isNaN(parsed.getTime()) ? new Date() : parsed
}

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

export function buildRecordsQuery(filters: RecordFilters, today: DateBase = new Date()): RecordsQuery {
  const query: RecordsQuery = {
    page: filters.page,
    per_page: filters.perPage,
    sort: 'desc',
  }

  const base = resolveBaseDate(today)
  const y = base.getFullYear()
  const m = base.getMonth() + 1

  if (filters.preset === 'custom' && filters.customStart && filters.customEnd && !isReversed(filters.customStart, filters.customEnd)) {
    query.start_date = filters.customStart
    query.end_date = filters.customEnd
  } else if (filters.preset === 'week') {
    query.start_date = toLocalDate(mondayOf(base))
    query.end_date = toLocalDate(base)
  } else if (filters.preset === 'today') {
    query.year = y
    query.month = m
    query.production_date = toLocalDate(base)
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
 *
 * 基准日期的口径与列表查询一致（第二个参数同样接受页面选中日期）：
 * 抽屉里「看到的是选中日所在月、导出的是当前自然月」是同一个缺陷的两面。
 */
export function buildExportRange(filters: RecordFilters, today: DateBase = new Date()): { start_date: string; end_date: string } {
  const base = resolveBaseDate(today)
  if (filters.preset === 'custom' && filters.customStart && filters.customEnd && !isReversed(filters.customStart, filters.customEnd)) {
    return { start_date: filters.customStart, end_date: filters.customEnd }
  }
  if (filters.preset === 'week') {
    return { start_date: toLocalDate(mondayOf(base)), end_date: toLocalDate(base) }
  }
  if (filters.preset === 'today') {
    const day = toLocalDate(base)
    return { start_date: day, end_date: day }
  }
  // 'month'，以及自定义区间填了一半/填反时的回退
  const first = new Date(base.getFullYear(), base.getMonth(), 1)
  const last = new Date(base.getFullYear(), base.getMonth() + 1, 0)
  return { start_date: toLocalDate(first), end_date: toLocalDate(last) }
}
