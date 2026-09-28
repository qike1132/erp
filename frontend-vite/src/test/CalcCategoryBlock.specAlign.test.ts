import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'

import CalcCategoryBlock from '@/views/material-calculator/components/CalcCategoryBlock.vue'
import type { MaterialCalcRow } from '@/api'

/**
 * 物料用量结果表 —— 「规格/色号」列对齐回归锁
 *
 * 背景：该表原先只有「总采购量」（.is-num）居中，「规格/色号」等文本列一律左对齐，
 * 色号/克重这类短串贴着左边界，与中轴上的数值列不成一条线。现改为与表头同轴居中。
 *
 * 断言口径：居中由 app.css 的 `.mc-table th.is-center / td.is-center` 提供，
 * jsdom 不加载外部样式表，故这里锁的是**类名的落位**（表头与数据同一列都带），
 * 以及「只有这一列被居中」——防止日后顺手把文本主列也一锅端居中。
 */

function row(over: Partial<MaterialCalcRow> & { __rk: string }): MaterialCalcRow & { __rk: string } {
  return {
    supplier_name: '苏州锦华纺织',
    material_name: '里布涤纶塔夫绸',
    specification: '110g/m²·米白',
    total_quantity: 128.5,
    unit: '米',
    ...over,
  }
}

function mountBlock(rows: (MaterialCalcRow & { __rk: string })[]) {
  return mount(CalcCategoryBlock, {
    props: { categoryKey: 'fabric', label: '布料', icon: 'chart-pie', rows, collapsed: false },
  })
}

describe('CalcCategoryBlock「规格/色号」列居中', () => {
  it('表头「规格/色号」带 .is-center，位置仍是第 3 列', () => {
    const wrapper = mountBlock([row({ __rk: 'a' })])
    const headers = wrapper.findAll('thead th')
    expect(headers.map((h) => h.text())).toEqual(['供应商', '物料名称', '规格/色号', '总采购量', '单位'])
    expect(headers[2]!.classes()).toContain('is-center')
  })

  it('数据行的规格单元格与表头同带 .is-center（表头/数据同轴）', () => {
    const wrapper = mountBlock([row({ __rk: 'a' })])
    const tds = wrapper.findAll('tbody tr')[0]!.findAll('td')
    expect(tds[2]!.text()).toBe('110g/m²·米白')
    expect(tds[2]!.classes()).toContain('is-center')
  })

  it('规格为空时回落「-」仍居中（不因占位符丢掉类名）', () => {
    const wrapper = mountBlock([row({ __rk: 'a', specification: '' })])
    const tds = wrapper.findAll('tbody tr')[0]!.findAll('td')
    expect(tds[2]!.text()).toBe('-')
    expect(tds[2]!.classes()).toContain('is-center')
  })

  it('文本主列（供应商/物料名称/单位）不被居中，只有规格列用 .is-center', () => {
    const wrapper = mountBlock([row({ __rk: 'a' })])
    const headers = wrapper.findAll('thead th')
    for (const i of [0, 1, 4]) expect(headers[i]!.classes()).not.toContain('is-center')
    // 数值列对齐契约不变：仍走 .is-num
    expect(headers[3]!.classes()).toContain('is-num')
    expect(headers[3]!.classes()).not.toContain('is-center')

    const tds = wrapper.findAll('tbody tr')[0]!.findAll('td')
    for (const i of [0, 1, 4]) expect(tds[i]!.classes()).not.toContain('is-center')
    expect(tds[3]!.classes()).toContain('is-num')
  })
})
