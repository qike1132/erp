/**
 * 数量差异对照块（2026-09-30）。
 *   D1 无差异 → 组件不渲染任何内容（父组件据此不占高度）
 *   D2 有差异 → 渲染横幅（列出不一致的物料与两个数值）+ 落库真值行，不一致者描红
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import SummaryDiffBlock from '@/views/purchase/components/SummaryDiffBlock.vue'

const stored = [
  { fabric_name: '共享布', specification: 'S1', unit: '米', quantity: 65 },
  { fabric_name: 'A专有布', specification: 'S2', unit: '米', quantity: 20 },
]

describe('SummaryDiffBlock', () => {
  it('D1 无差异 → 不渲染', () => {
    const w = mount(SummaryDiffBlock, { props: { diffs: [], storedFabrics: stored } })
    expect(w.text()).toBe('')
  })

  it('D2 有差异 → 横幅点名物料与数值，真值行渲染且不一致者描红', () => {
    const w = mount(SummaryDiffBlock, {
      props: { diffs: [{ materialName: '共享布', perSku: 60, stored: 65 }], storedFabrics: stored },
    })

    expect(w.text()).toContain('共享布')
    expect(w.text()).toContain('60')
    expect(w.text()).toContain('65')
    expect(w.text()).toContain('实际下单')
    // 不一致的那一行有描红标记
    expect(w.find('[data-diff="true"]').exists()).toBe(true)
    expect(w.findAll('[data-diff="true"]')).toHaveLength(1)
  })
})
