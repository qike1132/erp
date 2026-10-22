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

  it('silences canceled errors so callers do not toast', async () => {
    let settled = false
    const p = _silenceCanceled(Promise.reject({ code: 'ERR_CANCELED' }))
    p.then(
      () => { settled = true },
      () => { settled = true },
    )
    await Promise.resolve()
    await Promise.resolve()
    expect(settled).toBe(false)
  })

  it('passes through real errors', async () => {
    await expect(_silenceCanceled(Promise.reject(new Error('boom')))).rejects.toThrow('boom')
  })
})
