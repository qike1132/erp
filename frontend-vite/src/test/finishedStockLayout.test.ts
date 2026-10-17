/**
 * 成品库存页表格贴边回归测试
 *
 * 表格容器用 fs-card-main（自带 padding:0 的 flex 列），**不**用 page-card-body
 *（后者带 20/24 内边距 + scrollbar-gutter 预留槽，会留出四边空隙）。对齐 /stock
 * 的 sk-card-main。这里锁死该结构与 padding 归零，避免回归。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const src = readFileSync(
  resolve(process.cwd(), 'src/views/finished-stock/FinishedStockView.vue'),
  'utf-8',
)

describe('成品库存表格贴卡片边', () => {
  it('表格容器是 fs-card-main，不用 page-card-body', () => {
    expect(src).toContain('<div class="fs-card-main">')
    expect(src).not.toContain('page-card-body fs-table-body')
    expect(src).not.toContain('class="page-card-body">')
  })

  it('fs-card-main 是 padding:0 的 flex 列', () => {
    expect(src).toMatch(/\.fs-card-main\s*\{[^}]*padding:\s*0\s*;/)
    expect(src).toMatch(/\.fs-card-main\s*\{[^}]*display:\s*flex/)
  })

  it('不再残留 fs-table-body 归零规则', () => {
    expect(src).not.toContain('.fs-table-body')
  })
})
