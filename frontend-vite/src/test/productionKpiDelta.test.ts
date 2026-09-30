import { describe, expect, it } from 'vitest'

import { formatDelta } from '@/views/production/composables/kpiDelta'

describe('formatDelta', () => {
  it('增长显示 +x.x% 且为 up', () => {
    expect(formatDelta(112, 100)).toEqual({ text: '+12.0%', tone: 'up' })
  })

  it('下降显示 -x.x% 且为 down', () => {
    expect(formatDelta(90, 100)).toEqual({ text: '-10.0%', tone: 'down' })
  })

  it('持平显示 0.0% 且为 flat', () => {
    expect(formatDelta(100, 100)).toEqual({ text: '0.0%', tone: 'flat' })
  })

  it('分母为 0 时显示破折号，绝不出现 Infinity 或 NaN', () => {
    // Review Focus #2：昨天没生产、或刚上线没数据时，分母就是 0
    expect(formatDelta(50, 0)).toEqual({ text: '—', tone: 'flat' })
    expect(formatDelta(0, 0)).toEqual({ text: '—', tone: 'flat' })
  })

  it('分子为 0 而分母非 0 时是 -100%', () => {
    expect(formatDelta(0, 80)).toEqual({ text: '-100.0%', tone: 'down' })
  })

  it('非有限数值一律退化为破折号', () => {
    expect(formatDelta(Number.NaN, 100)).toEqual({ text: '—', tone: 'flat' })
    expect(formatDelta(100, Number.NaN)).toEqual({ text: '—', tone: 'flat' })
  })
})
