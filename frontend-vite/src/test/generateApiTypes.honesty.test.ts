import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..')

describe('生成物诚实性', () => {
  const dts = readFileSync(resolve(root, 'src/types/api.d.ts'), 'utf-8')

  it('list[dict] 响应产出 Record<string, unknown> 而非伪装的具体字段', () => {
    // OrderListResponse.data: list[dict]，实测 handler 注入 5 个字段 schema 看不见。
    // required=["data"] 已实测，故 data 必填、不带 ?。
    const m = /export interface OrderListResponse \{([\s\S]*?)\n\}/.exec(dts)
    expect(m).not.toBeNull()
    expect(m![1]).toMatch(/^\s+data: Array<Record<string, unknown>>$/m)
  })

  it('注入字段不出现在生成物里（生成层不假装覆盖）', () => {
    const item = /export interface OrderItemSchema \{([\s\S]*?)\n\}/.exec(dts)
    expect(item).not.toBeNull()
    for (const f of ['product_image', 'purchase_order_qty', 'spare_quantity', 'is_ordered', 'has_processes']) {
      expect(item![1]).not.toContain(f)
    }
  })

  it('撞名的 schema 产出两个不同的标识符，未静默合并', () => {
    // staging 与 production_plan 各有一个 StagingListResponse（结构不同）
    expect(dts).toMatch(/export interface staging_StagingListResponse \{/)
    expect(dts).toMatch(/export interface production_plan_StagingListResponse \{/)
  })
})

describe('前端视图模型未被删（生成物不覆盖它们）', () => {
  const handwritten = readFileSync(resolve(root, 'src/types/index.ts'), 'utf-8')

  it('会丢字段的前端视图模型仍在手写层', () => {
    // 这批名字与后端 schema 同名但结构不同（含前端自加字段），必须保留手写
    for (const name of ['MonthlySummary', 'NavSection', 'NavItem']) {
      expect(handwritten).toMatch(new RegExp(`export interface ${name}\\b`))
    }
    expect(handwritten).toMatch(/daily_data/) // MonthlySummary 的前端聚合字段
  })
})
