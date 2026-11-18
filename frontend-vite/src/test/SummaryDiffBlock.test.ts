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
  { supplierName: '供应商甲', fabricName: '共享布', partName: '身体', partDisplay: '身体', roleDisplay: '角色A', specification: 'S1', unit: '米', rate: 500, displayQuantity: 98, isSupplierFirst: true, supplierSpan: 2 },
  { supplierName: '供应商甲', fabricName: 'A专有布', partName: '', partDisplay: '', roleDisplay: '', specification: 'S2', unit: '米', rate: 10, displayQuantity: 21, isSupplierFirst: false, supplierSpan: 2 },
]

describe('SummaryDiffBlock', () => {
  it('D1 无差异 → 不渲染', () => {
    const w = mount(SummaryDiffBlock, { props: { diffs: [], storedRows } })
    expect(w.text()).toBe('')
  })

  it('D2 有差异 → 横幅点名物料与数值；数据行 10 列对齐主表，率取快照率、数量为加放派生值，不一致者描红', () => {
    const w = mount(SummaryDiffBlock, {
      props: { diffs: [{ materialName: '共享布', partName: '身体', perSku: 60, stored: 65 }], storedRows },
    })

    // 横幅：物料名 + 两个数值
    expect(w.text()).toContain('共享布')
    // F1-3（2026-10-17 审计）+ 2026-11-18 评审：
    // ① 子串断言下 600/6000 也「包含 60」；`\b` 能挡住数字相邻，但挡不住千分位
    //    （`\b60\b` 命中 "60,000"），所以直接锁横幅元素；
    // ② 只断「两个数字各自出现过」时，把 perSku/stored 写反（推算 65 / 实际 60）也绿 ——
    //    这里的正则把顺序与标签一起锁住。期望值由 diffs 手写：perSku=60、stored=65，
    //    模板（SummaryDiffBlock.vue）固定输出「（推算 60 / 实际 65）」。
    expect(w.find('tr.sm-diff-banner').text()).toMatch(
      /推算\s*60(?:\.0+)?\s*\/\s*实际\s*65(?:\.0+)?/,
    )
    expect(w.text()).toContain('实际下单')

    const dataRows = w.findAll('tr.sm-diff-row')
    expect(dataRows).toHaveLength(2)

    // 首行 = 标签(colspan=2，跨全部行) + 角色名称 + 订单数量(空) + 备品数量(空) + 部位 + 供应商 + 布料名 + 规格 + 损耗率 + 数量 + 单位 → 2+1+1+1+1+1+5 = 12 列
    // （列序 2026-11-08：角色名称在订单数量左边）
    const first = dataRows[0]!.findAll('td')
    expect(first).toHaveLength(11)
    expect(first[0]!.attributes('colspan')).toBe('2')
    expect(first[0]!.attributes('rowspan')).toBe('2')
    expect(first[0]!.text()).toContain('实际下单')
    // 列序与主表一致：角色名称 → 订单数量(空) → 备品数量(空) → 产品部位 → 供应商
    expect(first[1]!.text()).toBe('角色A')
    expect(first[2]!.text()).toBe('')
    expect(first[3]!.text()).toBe('')
    expect(first[4]!.text()).toBe('身体')
    expect(first[5]!.text()).toBe('供应商甲')
    expect(first[5]!.attributes('rowspan')).toBe('2')
    // 后 5 格与主表列序一致：布料名称 / 规格型号 / 损耗率 / 数量 / 单位
    expect(first.slice(6).map((td) => td.text())).toEqual(['共享布', 'S1', '500.0', '98', '米'])

    // 次行：标签与供应商被 rowspan 覆盖 → 只剩 角色 + 订单(空) + 备品(空) + 部位 + 后 5 格
    const second = dataRows[1]!.findAll('td')
    expect(second).toHaveLength(9)
    expect(second.map((td) => td.text())).toEqual(['', '', '', '', 'A专有布', 'S2', '10.0', '21', '米'])

    // 不一致行才带 data-diff；非差异行不渲染该属性（不留 data-diff="false" 噪声）
    expect(w.findAll('[data-diff="true"]')).toHaveLength(1)
    expect(dataRows[0]!.attributes('data-diff')).toBe('true')
    expect(dataRows[1]!.attributes('data-diff')).toBeUndefined()
  })
})
