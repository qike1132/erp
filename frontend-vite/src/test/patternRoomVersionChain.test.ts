/** 板房版本详情链路已无渲染消费，不得重新接回自动拉取（审计 M-12）。 */
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = readFileSync('src/views/pattern-room/PatternRoomView.vue', 'utf-8')

describe('板房版本详情链路', () => {
  it('不再自动实例化 useSamplingVersion，也不传两个未声明的死 props', () => {
    expect(source).not.toContain('useSamplingVersion')
    expect(source).not.toContain(':version-list=')
    expect(source).not.toContain(':version-loading=')
  })
})
