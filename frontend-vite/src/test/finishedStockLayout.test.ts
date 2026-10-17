/**
 * 成品库存页表格贴边回归测试
 *
 * .page-card-body 自带 padding: 20px 24px（app.css，给有内边距的内容页用）；
 * 本页表格容器加 .fs-table-body 把 padding 归零，避免表格左侧与卡片边框出现空隙
 * （观感对齐 /stock）。这里锁死该覆盖存在。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const src = readFileSync(
  resolve(process.cwd(), 'src/views/finished-stock/FinishedStockView.vue'),
  'utf-8',
)

describe('成品库存表格贴边', () => {
  it('表格容器同时挂 page-card-body 与 fs-table-body', () => {
    expect(src).toContain('page-card-body fs-table-body')
  })

  it('fs-table-body 把 padding 归零', () => {
    expect(src).toMatch(/\.fs-table-body\s*\{\s*padding:\s*0\s*;?\s*\}/)
  })
})
