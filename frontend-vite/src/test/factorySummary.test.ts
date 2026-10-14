/**
 * factorySummary —— /purchase-plan 月度汇总「按工厂汇总」的数据层纯函数。
 *
 * 钉住两件事：
 *   1. buildFactorySummary —— 把 customers[].factories 累加成每厂一行（顺序走 orderFactories）；
 *   2. totalFactorySummary —— 各厂求和，pct 不除零。
 * 纯函数，无需挂 PrimeVue。
 */
import { describe, it, expect } from 'vitest'
import { buildFactorySummary, totalFactorySummary } from '@/views/purchase-plan/components/factorySummary'
import type { CustSumItem } from '@/views/purchase-plan/components/types'

// 形状对齐 purchasePlanFactorySplit.test.ts 里的 CUST（客户级 factories 桶）
const CUST: CustSumItem[] = [
  {
    customer_id: 1, customer_name: '客户甲', plan_qty: 150, inventory_qty: 0,
    produced_qty: 120, remaining_qty: 30, warning_count: 0,
    factories: {
      '东莞': { plan_qty: 100, inventory_qty: 0, produced_qty: 100, remaining_qty: 0, warning_count: 0 },
      '湖北': { plan_qty: 50, inventory_qty: 0, produced_qty: 20, remaining_qty: 30, warning_count: 0 },
    },
  },
]

describe('buildFactorySummary', () => {
  it('按 customers[].factories 聚合：东莞 plan100 produced100 / 湖北 plan50 produced20', () => {
    const rows = buildFactorySummary(CUST)
    expect(rows.map(r => r.factory)).toEqual(['东莞', '湖北'])
    expect(rows[0]!.pct).toBe(100)
    expect(rows[1]!.pct).toBe(40)
  })

  it('无 factories 字段的客户被安全跳过', () => {
    const noFac: CustSumItem = {
      customer_id: 2, customer_name: '客户乙', plan_qty: 10, inventory_qty: 0,
      produced_qty: 0, remaining_qty: 10, warning_count: 0,
    }
    const rows = buildFactorySummary([noFac])
    expect(rows).toEqual([])
  })

  it('空输入不除零', () => {
    const rows = buildFactorySummary([])
    expect(rows).toEqual([])
    expect(totalFactorySummary(rows).pct).toBe(0)
  })
})

describe('totalFactorySummary', () => {
  it('合计 = 各厂之和', () => {
    const total = totalFactorySummary(buildFactorySummary(CUST))
    expect(total.plan).toBe(150)
    expect(total.produced).toBe(120)
    expect(total.pct).toBe(80)
  })
})
