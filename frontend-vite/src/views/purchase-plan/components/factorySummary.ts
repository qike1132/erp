import { orderFactories } from './factoryMeta'
import type { CustSumItem } from './types'

export interface FactorySummaryRow { factory: string; plan: number; produced: number; pct: number }

export function buildFactorySummary(customers: CustSumItem[]): FactorySummaryRow[] {
  const agg: Record<string, { plan: number; produced: number }> = {}
  for (const c of customers) {
    for (const [f, a] of Object.entries(c.factories ?? {})) {
      const g = agg[f] ?? (agg[f] = { plan: 0, produced: 0 })
      g.plan += Number(a.plan_qty || 0)
      g.produced += Number(a.produced_qty || 0)
    }
  }
  return orderFactories(Object.keys(agg)).map(f => {
    const g = agg[f]!
    return { factory: f, plan: g.plan, produced: g.produced,
      pct: g.plan > 0 ? Math.floor(g.produced / g.plan * 1000) / 10 : 0 }
  })
}

export function totalFactorySummary(rows: FactorySummaryRow[]): FactorySummaryRow {
  const plan = rows.reduce((n, r) => n + r.plan, 0)
  const produced = rows.reduce((n, r) => n + r.produced, 0)
  return { factory: '合计', plan, produced,
    pct: plan > 0 ? Math.floor(produced / plan * 1000) / 10 : 0 }
}
