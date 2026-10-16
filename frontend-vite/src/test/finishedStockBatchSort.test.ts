/**
 * 成品库存 — 批次号排序测试
 *
 * 批次号格式：0464(固定) + 年 + 年内第几天 + 序号，共 10 位定长数字串。
 * 用户要求：同一 SKU 的批次从小到大依次排序（= 生产时间正序）。
 */
import { describe, it, expect } from 'vitest'
import { batchSortKey, compareBatchNo } from '@/views/finished-stock/batchSort'

describe('批次号排序（0464 固定 + 年 + 年内第几天 + 序号）', () => {
  it('同一天不同序号：01 < 02', () => {
    expect(batchSortKey('0464628801') < batchSortKey('0464628802')).toBe(true)
  })

  it('同一年不同天：288 < 291 < 294', () => {
    const list = ['0464629401', '0464628801', '0464629101']
    expect([...list].sort(compareBatchNo)).toEqual(['0464628801', '0464629101', '0464629401'])
  })

  it('完整升序（含序号）', () => {
    const list = ['0464629401', '0464629102', '0464628801', '0464629101']
    expect([...list].sort(compareBatchNo)).toEqual([
      '0464628801', '0464629101', '0464629102', '0464629401',
    ])
  })

  it('空批次排到最后，不破坏数字批次排序', () => {
    const list = ['0464629101', '', '0464628801']
    expect([...list].sort(compareBatchNo)).toEqual(['0464628801', '0464629101', ''])
  })

  it('非数字批次不抛错、排到数字之后', () => {
    const list = ['B-2026-A', '0464628801']
    expect([...list].sort(compareBatchNo)).toEqual(['0464628801', 'B-2026-A'])
  })

  it('null/undefined 安全（不抛错，排最后）', () => {
    const list = [null, '0464628801', undefined]
    expect(() => [...list].sort(compareBatchNo)).not.toThrow()
    expect([...list].sort(compareBatchNo)[0]).toBe('0464628801')
  })
})
