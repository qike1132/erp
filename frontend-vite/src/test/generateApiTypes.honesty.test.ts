import { describe, it, expect } from 'vitest'
// 源码级断言：用 Vite 的 ?raw 读原文（bundle 层门禁——这些文件必须能被 esbuild 正常打包/解析）。
// 刻意不用 node:fs 的 readFileSync：那会让门禁停在非捆绑层。
import apiDts from '@/types/api.d.ts?raw'
import typesIndexSource from '@/types/index.ts?raw'
import sidebarNavSource from '@/layouts/composables/useSidebarNav.ts?raw'
import summaryModalSource from '@/views/purchase/composables/useSummaryModal.ts?raw'
import purchaseApiSource from '@/api/purchase.ts?raw'
import auxiliaryApiSource from '@/api/auxiliary.ts?raw'
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
  // 这批名字与后端 schema 同名但结构不同（含前端自加字段），必须保留手写。
  // spec 点名的 8 个名字实测分散在 8 个文件 / 9 处声明：NavItem / NavSection 各两份
  // （layouts/composables/useSidebarNav.ts 与 types/index.ts 各一）。
  const handwritten: Record<string, { source: string; names: string[] }> = {
    'src/layouts/composables/useSidebarNav.ts': { source: sidebarNavSource, names: ['NavItem', 'NavSection'] },
    'src/types/index.ts': { source: typesIndexSource, names: ['NavSection', 'NavItem', 'MonthlySummary'] },
    'src/views/purchase/composables/useSummaryModal.ts': { source: summaryModalSource, names: ['FabricItem'] },
    'src/api/purchase.ts': { source: purchaseApiSource, names: ['ProductListResponse'] },
    'src/api/auxiliary.ts': { source: auxiliaryApiSource, names: ['AvailableStockinItem'] },
    'src/views/customer-order/composables/types.ts': { source: customerOrderTypesSource, names: ['AvailableStockinItem'] },
  }

  it('会丢字段的前端视图模型仍在手写层（逐文件断言，覆盖全部 8 个名字）', () => {
    for (const [file, { source, names }] of Object.entries(handwritten)) {
      for (const name of names) {
        expect(source, `${file} 缺少手写声明 ${name}`).toMatch(new RegExp(`export interface ${name}\\b`))
      }
    }
    // MonthlySummary 的前端聚合字段（后端 schema 不含）
    expect(typesIndexSource).toMatch(/daily_data/)
  })
})
