import { describe, it, expect } from 'vitest'
// 源码级断言：用 Vite 的 ?raw 读原文（bundle 层门禁——这些文件必须能被 esbuild 正常打包/解析）。
// 刻意不用 node:fs 的 readFileSync：那会让门禁停在非捆绑层。
import apiDts from '@/types/api.d.ts?raw'
import typesIndexSource from '@/types/index.ts?raw'
import sidebarNavSource from '@/layouts/composables/useSidebarNav.ts?raw'
import summaryModalSource from '@/views/purchase/composables/useSummaryModal.ts?raw'
import purchaseApiSource from '@/api/purchase.ts?raw'
import customerOrderTypesSource from '@/views/customer-order/composables/types.ts?raw'

describe('生成物诚实性', () => {
  it('list[dict] 响应产出 Record<string, unknown> 而非伪装的具体字段', () => {
    // OrderListResponse.data: list[dict]，实测 handler 注入 5 个字段 schema 看不见。
    // required=["data"] 已实测，故 data 必填、不带 ?。
    const m = /export interface OrderListResponse \{([\s\S]*?)\n\}/.exec(apiDts)
    expect(m).not.toBeNull()
    expect(m![1]).toMatch(/^\s+data: Array<Record<string, unknown>>$/m)
  })

  it('注入字段不出现在生成物里（生成层不假装覆盖）', () => {
    const item = /export interface OrderItemSchema \{([\s\S]*?)\n\}/.exec(apiDts)
    expect(item).not.toBeNull()
    for (const f of ['product_image', 'purchase_order_qty', 'spare_quantity', 'is_ordered', 'has_processes']) {
      expect(item![1]).not.toContain(f)
    }
  })

  it('撞名的 schema 产出两个不同的标识符，未静默合并', () => {
    // staging 与 production_plan 各有一个 StagingListResponse（结构不同）
    expect(apiDts).toMatch(/export interface staging_StagingListResponse \{/)
    expect(apiDts).toMatch(/export interface production_plan_StagingListResponse \{/)
  })
})

describe('前端视图模型未被删（生成物不覆盖它们）', () => {
  // 入选判据是「这份手写声明带了生成层没有的字段」——被生成物替换就会丢字段。
  // 只是字段名相同、结构也相同（至多断言必填）的那类不算，它们已迁成派生别名：
  // api/auxiliary.ts 的 AvailableStockinItem 曾经在这里，但 7 个字段与生成层逐字相同、
  // 只多一个 quantity 必填（2026-10-21 be9abaa9 迁成 WithRequired），属于该被迁走的一类，
  // 所以从本表移除；同名但真带 schema 没有的 deducted 的是 customer-order 那份。
  const handwritten: Record<string, { source: string; names: string[] }> = {
    'src/layouts/composables/useSidebarNav.ts': { source: sidebarNavSource, names: ['NavItem', 'NavSection'] },
    'src/types/index.ts': { source: typesIndexSource, names: ['NavSection', 'NavItem', 'MonthlySummary'] },
    'src/views/purchase/composables/useSummaryModal.ts': { source: summaryModalSource, names: ['FabricItem'] },
    'src/api/purchase.ts': { source: purchaseApiSource, names: ['ProductListResponse'] },
    'src/views/customer-order/composables/types.ts': { source: customerOrderTypesSource, names: ['AvailableStockinItem'] },
  }

  it('会丢字段的前端视图模型仍在手写层（逐文件断言，覆盖全部 8 处声明）', () => {
    for (const [file, { source, names }] of Object.entries(handwritten)) {
      for (const name of names) {
        expect(source, `${file} 缺少手写声明 ${name}`).toMatch(new RegExp(`export interface ${name}\\b`))
      }
    }
    // MonthlySummary 的前端聚合字段（后端 schema 不含）
    expect(typesIndexSource).toMatch(/daily_data/)
    // customer-order 那份 AvailableStockinItem 的 deducted（后端 schema 不含）
    const stockin = /export interface AvailableStockinItem \{([\s\S]*?)\n\}/.exec(customerOrderTypesSource)
    expect(stockin, 'customer-order 的 AvailableStockinItem 声明形态变了').not.toBeNull()
    expect(stockin![1]).toContain('deducted')
  })
})
