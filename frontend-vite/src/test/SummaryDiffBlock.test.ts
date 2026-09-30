/**
 * 数量差异对照块（2026-09-30）。
 *   D1 无差异 → 组件不渲染任何内容（父组件据此不占高度）
 *   D2 有差异 → 横幅点名物料与两个数值；数据行与主表 10 列对齐（标签跨 4 列 + 供应商 + 后 5 格），
 *              损耗率取该行快照率、数量为按该率加放后的派生值（与主表同源），不一致者描红
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import SummaryDiffBlock from '@/views/purchase/components/SummaryDiffBlock.vue'

/** 落库真值行（率/数量已由 composable 按主表口径算好）：共享布 65 @500‰ → ceil(97.5)=98；A专有布 20 @10‰ → ceil(20.2)=21 */
const storedRows = [
  { supplierName: '供应商甲', fabricName: '共享布', specification: 'S1', unit: '米', rate: 500, displayQuantity: 98, isSupplierFirst: true, supplierSpan: 2 },
  { supplierName: '供应商甲', fabricName: 'A专有布', specification: 'S2', unit: '米', rate: 10, displayQuantity: 21, isSupplierFirst: false, supplierSpan: 2 },
]

describe('SummaryDiffBlock', () => {
  it('D1 无差异 → 不渲染', () => {
    const w = mount(SummaryDiffBlock, { props: { diffs: [], storedRows } })
    expect(w.text()).toBe('')
  })

  it('D2 有差异 → 横幅点名物料与数值；数据行 10 列对齐主表，率取快照率、数量为加放派生值，不一致者描红', () => {
    const w = mount(SummaryDiffBlock, {
      props: { diffs: [{ materialName: '共享布', perSku: 60, stored: 65 }], storedRows },
    })

    // 横幅：物料名 + 两个数值
    expect(w.text()).toContain('共享布')
    expect(w.text()).toContain('60')
    expect(w.text()).toContain('65')
    expect(w.text()).toContain('实际下单')

    const dataRows = w.findAll('tr.sm-diff-row')
    expect(dataRows).toHaveLength(2)

    // 首行 = 标签(colspan=4，跨全部行) + 供应商 + 布料名 + 规格 + 损耗率 + 数量 + 单位 → 4+1+5 = 10 列
    const first = dataRows[0]!.findAll('td')
    expect(first).toHaveLength(7)
    expect(first[0]!.attributes('colspan')).toBe('4')
    expect(first[0]!.attributes('rowspan')).toBe('2')
    expect(first[0]!.text()).toContain('实际下单')
    expect(first[1]!.text()).toBe('供应商甲')
    expect(first[1]!.attributes('rowspan')).toBe('2')
    // 后 5 格与主表列序一致：布料名称 / 规格型号 / 损耗率 / 数量 / 单位
    expect(first.slice(2).map((td) => td.text())).toEqual(['共享布', 'S1', '500.0', '98', '米'])

    // 次行：标签与供应商被 rowspan 覆盖 → 只剩后 5 格
    const second = dataRows[1]!.findAll('td')
    expect(second).toHaveLength(5)
    expect(second.map((td) => td.text())).toEqual(['A专有布', 'S2', '10.0', '21', '米'])

    // 不一致行才带 data-diff；非差异行不渲染该属性（不留 data-diff="false" 噪声）
    expect(w.findAll('[data-diff="true"]')).toHaveLength(1)
    expect(dataRows[0]!.attributes('data-diff')).toBe('true')
    expect(dataRows[1]!.attributes('data-diff')).toBeUndefined()
  })
})
