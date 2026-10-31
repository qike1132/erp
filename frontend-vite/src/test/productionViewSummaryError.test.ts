/**
 * 生产驾驶舱的汇总失败态（2026-10-30 审计 A-M33）
 *
 * 现场：ProductionView 的四个汇总 query（今日/昨日/本月/上月）都没取 isError。
 * 请求失败时：KPI 条停在骨架屏（v-if="today && monthly" 永不成立）、部门卡片
 * 显示 0、趋势面板显示「暂无产量」——同屏出现三种互相矛盾的信号，且状态永不恢复。
 *
 * 修复后：四个 query 各取 isError + refetch，聚合成一个失败态横幅，并把
 * loadFailed 传给 CockpitKpiRow（运行时行为见 cockpitKpiRow.render.test.ts）。
 * 这里锁住 ProductionView 侧的三件事：取 isError、横幅可重试、KPI 收到 loadFailed。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const src = readFileSync(
  resolve(process.cwd(), 'src/views/production/ProductionView.vue'),
  'utf-8',
)

describe('ProductionView 汇总失败态', () => {
  it('四个汇总 query 都取 isError 与 refetch', () => {
    for (const name of ['dailyError', 'yesterdayError', 'monthlyError', 'previousMonthError']) {
      expect(src, `${name} 应来自 useQuery 的 isError`).toContain(`isError: ${name}`)
    }
    for (const fn of ['refetchDaily', 'refetchYesterday', 'refetchMonthly', 'refetchPreviousMonth']) {
      expect(src, `${fn} 应来自 useQuery 的 refetch`).toContain(`refetch: ${fn}`)
    }
  })

  it('失败态横幅带 role=alert，重试会重取四个 query', () => {
    expect(src).toMatch(/v-if="summaryLoadError"[\s\S]{0,400}?role="alert"/)
    expect(src).toContain('生产汇总数据加载失败')
    const retryFn = src.match(/async function retrySummaries\(\) \{[\s\S]*?\n\}/)
    expect(retryFn, '必须有 retrySummaries').not.toBeNull()
    for (const fn of ['refetchDaily()', 'refetchYesterday()', 'refetchMonthly()', 'refetchPreviousMonth()']) {
      expect(retryFn![0]).toContain(fn)
    }
  })

  it('KPI 行收到 loadFailed 与 retry', () => {
    expect(src).toContain(':load-failed="summaryLoadError"')
    expect(src).toContain('@retry="retrySummaries"')
  })
})
