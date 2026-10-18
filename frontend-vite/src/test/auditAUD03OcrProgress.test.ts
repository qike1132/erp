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
  it('读取 percent（后端字段）', () => {
    // 2026-10-18：percentage 是旧前端臆造的字段，后端从未返回，已删除读取
    expect(source).toMatch(/res\.percent\s*\?\?\s*0/)
  })

  it('done 先于 uploadResult 到达时不得提前锁存成功', () => {
    // 后端在上传响应返回前就写 done；轮询必须先等 uploading 结束
    expect(source).toMatch(/if \(uploading\.value\)/)
  })

  it('逐文件提交（请求体 10MB 上限），共用同一 task_id', () => {
    // 整批塞一个请求会被中间件/nginx 的 10MB 挡下
    expect(source).toMatch(/fd\.append\('files', file\)/)
    expect(source).toMatch(/ocrApi\.upload\(sid, fd, sid\)/)
  })

  it('上传期间禁用选择器且轮询只跳过文案、仍更新百分比', () => {
    expect(source).toMatch(/:disabled="uploading"/)
    expect(source).toMatch(/if \(uploading\.value\) \{\s*progress\.value = res\.percent/)
  })

  it('单文件失败区分「明确拒绝」与「结果未知」', () => {
    expect(source).toMatch(/status === undefined \|\| status >= 500/)
  })

  it('前端校验后端 MAX_OCR_FILES=50', () => {
    expect(source).toMatch(/MAX_FILES = 50/)
  })

  it('终态集合包含 done 与 not_found', () => {
    expect(source).toMatch(/OCR_TERMINAL_STATUSES\s*=\s*\[[^\]]*'done'[^\]]*'not_found'/)
  })

  it('轮询按终态集合停止', () => {
    expect(source).toMatch(/OCR_TERMINAL_STATUSES\.includes\(data\.status\)/)
  })
})
