import { describe, expect, it } from 'vitest'
import {
  _silenceCanceled,
  abortPendingRequests,
  createTrackedController,
} from '@/api/request'

describe('request abort', () => {
  it('aborts all tracked controllers', () => {
    const a = createTrackedController()
    const b = createTrackedController()
    abortPendingRequests()
    expect(a.signal.aborted).toBe(true)
    expect(b.signal.aborted).toBe(true)
  })

  it('取消必须正常 settle（reject），调用方才能结束 fetching', async () => {
    // H8：旧实现返回永不 settle 的 Promise，Vue Query 会永久停在 fetching。
    // 现在取消以 CanceledError reject，展示层自行用 isCanceledError 过滤。
    const canceled = { code: 'ERR_CANCELED' }
    await expect(_silenceCanceled(Promise.reject(canceled))).rejects.toBe(canceled)
  })

  it('passes through real errors', async () => {
    await expect(_silenceCanceled(Promise.reject(new Error('boom')))).rejects.toThrow('boom')
  })
})
