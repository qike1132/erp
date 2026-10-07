import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'

import CalcResultColumn from '@/views/material-calculator/components/CalcResultColumn.vue'
import type { MaterialCalcRow, MaterialCalcScopeGroup } from '@/api'

/**
 * 物料计算器「汇总」TAB（方案 A，mockups/material-calc-summary-2026-09-29.html）。
 *
 * 多 SKU 录入时结果列不再只按产品分 TAB——「汇总」TAB 恒居首位且默认选中，
 * 相同「供应商 + 物料名称 + 规格/色号」的行合并为一行、数量相加；
 * 「按产品查看」降级为后续 TAB，多角色 BOM 能力保留。
 *
 * 本机开不了浏览器预览：结构用挂载测试固化（汇总 TAB 首位/默认选中/合并行/
 * 切回产品 TAB 仍是分块渲染），排版靠用户实测。
 */

function row(over: Partial<MaterialCalcRow>): MaterialCalcRow {
  return { supplier_name: '东莞恒泰填充材料', material_name: 'PP棉', specification: '7D三维卷曲', total_quantity: 0, unit: 'kg', ...over }
}

function group(over: Partial<MaterialCalcScopeGroup>): MaterialCalcScopeGroup {
  return {
    product_id: 1,
    product_name: '招财猫盲盒毛绒挂件(混4款)',
    role_id: null,
    role_name: '默认BOM',
    quantity: 500,
    filling: [],
    fabric: [],
    accessory: [],
    packaging: [],
    ...over,
  }
}

const TWO_SKU_GROUPS: MaterialCalcScopeGroup[] = [
  group({
    product_id: 1, quantity: 500,
    filling: [row({ total_quantity: 40 })],
    fabric: [row({ supplier_name: '苏州锦华纺织', material_name: '短毛绒', specification: '110g/m²·米白', total_quantity: 125, unit: '米' })],
  }),
  group({
    product_id: 2, product_name: '泰迪熊毛绒玩具(25cm)', quantity: 300,
    filling: [row({ total_quantity: 30 })],
    fabric: [row({ supplier_name: '苏州锦华纺织', material_name: '短毛绒', specification: '110g/m²·米白', total_quantity: 105, unit: '米' })],
  }),
]

function mountColumn(groups: MaterialCalcScopeGroup[], calcResults: Record<string, MaterialCalcRow[]> = {}) {
  return mount(CalcResultColumn, {
    props: {
      calcResults,
      hasResults: Object.values(calcResults).some((arr) => arr.length > 0),
      calcGroups: groups,
    },
  })
}

describe('CalcResultColumn —— 「汇总」TAB（方案 A）', () => {
  it('多 SKU 时「汇总」TAB 恒居首位且默认选中', () => {
    const w = mountColumn(TWO_SKU_GROUPS)

    const tabs = w.findAll('[role="tab"]')
    expect(tabs.length).toBeGreaterThanOrEqual(3)
    expect(tabs[0]!.text()).toBe('汇总')
    expect(tabs[0]!.attributes('aria-selected')).toBe('true')
    expect(tabs[1]!.text()).toContain('招财猫')
    expect(tabs[2]!.text()).toContain('泰迪熊')
  })

  it('汇总视图：同供应商·物料·规格合并为一行，数量相加（40+30=70）', () => {
    const w = mountColumn(TWO_SKU_GROUPS)

    const fillingRows = w.findAll('.mc-category-block')[0]!.findAll('tbody tr')
    expect(fillingRows).toHaveLength(1)
    const cells = fillingRows[0]!.findAll('td')
    expect(cells[1]!.text()).toContain('PP棉')
    expect(cells[3]!.text()).toBe('70')
    // 汇总行不再渲染 SKU 徽标（2026-10-07 按要求移除）
    expect(fillingRows[0]!.text()).not.toContain('个SKU')
  })

  it('汇总视图：不再渲染「N 个SKU」徽标（2026-10-07 按要求移除）', () => {
    const w = mountColumn(TWO_SKU_GROUPS)

    expect(w.findAll('.mc-sku-badge')).toHaveLength(0)
    expect(w.text()).not.toContain('个SKU')
  })

  it('汇总视图：作用域条不再显示产品数/合计（2026-10-07 按要求移除）', () => {
    const w = mountColumn(TWO_SKU_GROUPS)

    expect(w.find('.mc-scope-meta').exists()).toBe(false)
    expect(w.find('.mc-scope-bar').text()).not.toContain('个产品')
  })

  it('合计项数按汇总口径计（合并后 2 项，不是 4 项）', () => {
    const w = mountColumn(TWO_SKU_GROUPS)

    expect(w.find('.mc-col-tail').text()).toContain('2')
  })

  it('点击产品 TAB 切回该产品的分块渲染（不再合并）', async () => {
    const w = mountColumn(TWO_SKU_GROUPS)

    const tabs = w.findAll('[role="tab"]')
    await tabs[1]!.trigger('click')

    expect(tabs[1]!.attributes('aria-selected')).toBe('true')
    const fillingRows = w.findAll('.mc-category-block')[0]!.findAll('tbody tr')
    expect(fillingRows).toHaveLength(1)
    expect(fillingRows[0]!.findAll('td')[3]!.text()).toBe('40') // 只显示该 SKU 自己的量
    expect(fillingRows[0]!.text()).not.toContain('个SKU')
  })

  it('单 SKU（单作用域）时无 TAB、无汇总逻辑，行为与旧版一致', () => {
    const single = [group({ filling: [row({ total_quantity: 40 })] })]
    const w = mountColumn(single)

    expect(w.find('[role="tab"]').exists()).toBe(false)
    expect(w.find('.mc-scope-name').text()).toBe('默认BOM')
    expect(w.text()).not.toContain('个SKU')
  })

  it('汇总视图的单位换算仍生效（克→kg）', () => {
    const groups = [
      group({ product_id: 1, quantity: 500, filling: [row({ total_quantity: 40000, unit: '克' })] }),
      group({ product_id: 2, product_name: '泰迪熊', quantity: 300, filling: [row({ total_quantity: 30000, unit: '克' })] }),
    ]
    const w = mountColumn(groups)

    const cells = w.findAll('.mc-category-block')[0]!.findAll('tbody tr')[0]!.findAll('td')
    expect(cells[3]!.text()).toBe('70')
    expect(cells[4]!.text()).toBe('kg')
  })
})
