import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'

import MMaterialCalculatorView from '@/mobile/views/material-calculator/MMaterialCalculatorView.vue'
import type { MaterialCalcRow, MaterialCalcScopeGroup } from '@/api'

/**
 * 移动端物料计算器「汇总」卡片（方案 A 的移动端同步）。
 *
 * 桌面端加了「汇总」TAB；移动端没有 TAB（是作用域卡片堆叠），
 * 对应改动 = 顶部多一张「汇总」卡片：相同供应商·物料·规格合并求和。
 * 多角色 BOM 的分块卡片保留在后。
 */

vi.mock('@/api', () => ({
  purchaseApi: {
    searchSuggestions: vi.fn().mockResolvedValue({ suggestions: [] }),
    calculate: vi.fn(),
  },
}))

vi.mock('@/composables/useToast', () => ({
  showToast: vi.fn(),
}))

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
  group({ product_id: 1, quantity: 500, filling: [row({ total_quantity: 40 })] }),
  group({ product_id: 2, product_name: '泰迪熊毛绒玩具(25cm)', quantity: 300, filling: [row({ total_quantity: 30 })] }),
]

async function mountView(calcGroups: MaterialCalcScopeGroup[], orderItems: { product_id: number; name: string; quantity: number }[] = []) {
  // useMaterialCalculator 每次 call 新建 refs；<script setup> 把它们暴露在 vm proxy 上
  //（直接赋值即响应式，但需 nextTick 等渲染——见挂载调试验证）。
  const wrapper = mount(MMaterialCalculatorView)
  const vm = wrapper.vm as unknown as {
    calcGroups: MaterialCalcScopeGroup[]
    orderItems: { product_id: number; name: string; quantity: number }[]
  }
  vm.calcGroups = calcGroups
  vm.orderItems = orderItems
  await nextTick()
  return wrapper
}

describe('MMaterialCalculatorView —— 「汇总」卡片（方案 A 移动端）', () => {
  it('多 SKU 时首张结果卡是「汇总」卡：合并行、数量相加（不再渲染 SKU 徽标）', async () => {
    const w = await mountView(TWO_SKU_GROUPS)

    const cards = w.findAll('.m-scope-card')
    expect(cards.length).toBeGreaterThanOrEqual(3) // 汇总 + 2 个产品
    const summaryCard = cards[0]!
    expect(summaryCard.find('.m-scope-badge').text()).toBe('汇总')
    expect(summaryCard.find('.m-scope-qty').text()).toContain('800') // 500 + 300

    const rows = summaryCard.findAll('.m-result-row')
    expect(rows).toHaveLength(1)
    expect(rows[0]!.find('.m-result-name').text()).toContain('PP棉')
    // SKU 徽标已按 2026-10-07 要求移除（桌面端同步）
    expect(rows[0]!.find('.m-result-name').text()).not.toContain('个SKU')
    expect(rows[0]!.find('.m-result-qty').text()).toContain('70') // 40 + 30
  })

  it('单 SKU 时不渲染汇总卡（无合并价值，避免冗余）', async () => {
    const w = await mountView([group({ filling: [row({ total_quantity: 40 })] })])

    const cards = w.findAll('.m-scope-card')
    expect(cards).toHaveLength(1)
    expect(cards[0]!.find('.m-scope-badge').text()).not.toBe('汇总')
    expect(w.text()).not.toContain('个SKU')
  })

  it('汇总卡按分类折叠分组，与产品卡结构一致', async () => {
    const w = await mountView(TWO_SKU_GROUPS)

    const summaryCard = w.findAll('.m-scope-card')[0]!
    const cats = summaryCard.findAll('.m-result-cat')
    expect(cats.length).toBeGreaterThanOrEqual(1)
    expect(cats[0]!.text()).toContain('填充类')
  })
})
