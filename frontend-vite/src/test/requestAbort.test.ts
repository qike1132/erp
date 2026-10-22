import { describe, expect, it } from 'vitest'
import { abortPendingRequests, createTrackedController } from '@/api/request'

describe('request abort', () => {
  it('aborts all tracked controllers', () => {
    const a = createTrackedController()
    const b = createTrackedController()
    abortPendingRequests()
    expect(a.signal.aborted).toBe(true)
    expect(b.signal.aborted).toBe(true)
  })
})
