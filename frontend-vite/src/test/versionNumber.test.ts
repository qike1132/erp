import { describe, expect, it } from 'vitest'
import { versionNumber } from '@/views/pattern-room/composables/usePartsVersionFilter'

describe('版本号数值序 helper', () => {
  it('解析 T 前缀与大小写', () => {
    expect(versionNumber('T1')).toBe(1)
    expect(versionNumber('t2')).toBe(2)
    expect(versionNumber('T10')).toBe(10)
  })

  it('空值与非法值排最后', () => {
    expect(versionNumber(undefined)).toBe(Number.MAX_SAFE_INTEGER)
    expect(versionNumber(null)).toBe(Number.MAX_SAFE_INTEGER)
    expect(versionNumber('bad')).toBe(Number.MAX_SAFE_INTEGER)
  })
})
