/**
 * 报表接口响应 DTO：流水行必须用生成层的具体类型，不得 `Record<string, unknown>` 兜底
 * （2026-11-16 上线前审计 Low）。
 *
 * 缺陷：api/report.ts 里 `logs: Record<string, unknown>[]`，于是手写的 `ReportLogItem`
 * 别名（PickRequired 出前端真正会读的字段）**全仓无人使用**——`logs` 的元素是任意键值袋，
 * 字段拼错、后端改名在编译期一律查不出来，也不会有任何测试变红。
 *
 * 修复：`ReportLogResponse` 改为复用生成层 `ReportResponse`（单一真相源，check:dto 的 R2
 * 只允许派生别名），logs 换成必填的 `ReportLogItem[]`，pagination 收成报表页真正读的形状。
 *
 * 本用例两层证据：
 *  1) 文本层——api/report.ts 里不再出现 `Record<string, unknown>`，且别名确实被 logs 使用；
 *  2) 类型层——下方 sample 常量必须能按 `ReportLogItem` 全字段赋值（类型被改坏 vue-tsc 直接红）。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { ReportLogItem, ReportLogResponse } from '@/api/report'

const here = dirname(fileURLToPath(import.meta.url)) // frontend-vite/src/test
const source = readFileSync(resolve(here, '..', 'api', 'report.ts'), 'utf-8')

/** 类型层证据：ReportLogItem 的必填口径真的来自生成层（少一个键 vue-tsc 即报错） */
const sampleLog: ReportLogItem = {
  record_id: 1, record_no: 'ST-20261116-0001', reason: '', gross_quantity: 0, note_display: '',
  order_id: 7, order_no: 'SO-20261116-0001', item_id: 12, item_count: 2, order_total_qty: 300,
  item_note: '', order_date: '2026-11-16 09:12', stockin_date: '', stockout_date: '',
  deduction_time: '', return_date: '', customer: 'MINISO国际', product_name: '鲨鱼公仔',
  product_barcode: '6901234567890', quantity: 150, note: '', order_note: '',
}
const samplePage: ReportLogResponse['pagination'] = { pages: 2, total: 40 }

describe('api/report.ts 响应 DTO', () => {
  it('不再用 Record<string, unknown> 兜底流水行与分页', () => {
    expect(source).not.toContain('Record<string, unknown>')
  })

  it('logs 用的是手写别名 ReportLogItem，且该别名派生自生成层 @/types/api', () => {
    // 别名真的被消费（否则删掉它也没人发现——这正是原缺陷）
    expect(source).toContain('logs: ReportLogItem[]')
    // 字段清单只有一份：从生成层 PickRequired（check:dto 的 R2 只放行这类派生别名）
    expect(source).toMatch(/export type ReportLogItem = PickRequired<GenReportLogItem,/)
    expect(source).toContain('ReportResponse as GenReportResponse')
  })

  it('ReportLogItem 是具体字段类型而非任意键值袋，分页形状可直接取值', () => {
    // 类型层：任意键值袋下这些取值不会是字面量类型；编译通过即证别名生效
    expect(sampleLog.order_no).toBe('SO-20261116-0001')
    expect(sampleLog.quantity).toBe(150)
    expect(samplePage.pages).toBe(2)
    expect(samplePage.total).toBe(40)
  })
})
