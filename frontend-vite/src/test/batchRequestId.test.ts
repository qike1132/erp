/** 批量提交每行幂等令牌：工厂稳定 + 两个批量入口均接线。 */
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import { createBatchRequestId } from '@/utils/batchRequestId'

describe('批量请求幂等令牌', () => {
  it('同一批次稳定、不同下标不同、不同批次不同', () => {
    const batch = createBatchRequestId('stockout')
    const a = batch(0)
    const b = batch(1)
    const nextBatch = createBatchRequestId('stockout')(0)

    expect(a).toBe(batch(0))
    expect(a).not.toBe(b)
    expect(a).not.toBe(nextBatch)
    expect(a.startsWith('stockout:')).toBe(true)
    expect(a.endsWith(':0')).toBe(true)
  })

  it('两个前端批量提交入口都传 request_id', () => {
    const stockOut = readFileSync(
      'src/views/stock/composables/useStockOutActions.ts', 'utf-8',
    )
    const stockIn = readFileSync(
      'src/views/customer-order/composables/useStagedItems.ts', 'utf-8',
    )

    expect(stockOut).toContain('request_id: nextRequestId(index)')
    expect(stockIn).toContain('request_id: nextRequestId(index)')
  })
})
