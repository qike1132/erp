import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 回归锁（2026-11-16 上线前审计 H-5）：退货管理页列表查询的门控必须与后端**同源**。
 *
 * 事故形态：`stock_return_manage`（「退货管理(全部)」）是 seed_nav 里的**顶层码**，
 * 与 `stock_return_view` 并列两个勾选框。后端 `User.has_permission` 对 `*_manage`
 * 会自动放行同名 `*_view`，导航侧 `nav_context` 也把两个码一起展开 —— 唯独前端列表
 * 查询用了严格 `hasPermission('stock_return_view')`，于是只授 manage 的账号：
 * 侧栏有入口、`canManage=true` 能建单，**列表却永远显示「暂无退货记录」**（query 被禁用）。
 *
 * 为什么用源码断言而不是挂载组件：这个 bug 的形状是「一行门控写错」，而挂载
 * StockReturnView 需要 6 个 PrimeVue 重组件 + auth store + vue-query 全量桩，
 * 成本远高于收益。这里把判定收敛到**唯一那一行**（`enabled:` 表达式），
 * 若有人改回单码，正则捕获到的表达式里就不再同时出现两个码 → 变红。
 */
const SOURCE = readFileSync(
  join(process.cwd(), 'src/views/stock-return/composables/useStockReturn.ts'),
  'utf8',
)

/** 抽出列表 query 的 `enabled:` 表达式（到第一个 `,` 换行为止）。 */
function enabledExpression(): string {
  const m = SOURCE.match(/enabled:\s*computed\(\(\)\s*=>[^\n]*/)
  expect(m, 'useStockReturn.ts 里找不到列表 query 的 enabled 门控').not.toBeNull()
  return (m as RegExpMatchArray)[0]
}

describe('退货列表门控与后端同源（H-5）', () => {
  it('enabled 表达式必须同时接受 stock_return_view 与 stock_return_manage', () => {
    const expr = enabledExpression()
    expect(expr).toContain('stock_return_view')
    expect(expr).toContain(
      'stock_return_manage',
    )
  })

  it('enabled 不能再退化成「只认 view」的单码严格判断', () => {
    const expr = enabledExpression()
    // 单码形态：auth.hasPermission('stock_return_view') 且不含 manage
    const singleCodeOnly =
      /hasPermission\(\s*'stock_return_view'\s*\)/.test(expr) && !expr.includes('stock_return_manage')
    expect(singleCodeOnly, `enabled 门控退化成单码：${expr}`).toBe(false)
  })
})
