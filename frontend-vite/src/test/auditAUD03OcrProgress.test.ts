/**
 * AUD-03 前端回归：OCR 进度必须读后端真实字段并识别终态（2026-10-17 审计）。
 *
 * 缺陷：后端写 done/percent，前端读 completed/percentage → 进度恒 0、
 * 终态永不命中、无限轮询；not_found 也不是终态。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const source = readFileSync(
  resolve(__dirname, '../views/ocr-import/OcrImportView.vue'),
  'utf-8',
)

describe('AUD-03 OCR 进度前端契约', () => {
  it('读取 percent（后端字段）而不是只读 percentage', () => {
    expect(source).toMatch(/res\.percent\s*\?\?\s*res\.percentage/)
  })

  it('终态集合包含 done 与 not_found', () => {
    expect(source).toMatch(/OCR_TERMINAL_STATUSES\s*=\s*\[[^\]]*'done'[^\]]*'not_found'/)
  })

  it('轮询按终态集合停止', () => {
    expect(source).toMatch(/OCR_TERMINAL_STATUSES\.includes\(data\.status\)/)
  })
})
