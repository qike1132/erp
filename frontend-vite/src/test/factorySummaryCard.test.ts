/**
 * 「按工厂汇总」卡片（FactorySummaryCard）—— 覆盖：
 *   1. 按 customers[].factories 聚合出每厂一格 + 末尾合计格；
 *   2. 完成率条按 0红/未满琥珀/满绿 上色；
 *   3. 无 factories 的客户只剩合计一格。
 * 纯展示组件，mount 时不需要 PrimeVue。
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import FactorySummaryCard from '@/views/purchase-plan/components/FactorySummaryCard.vue'
import type { CustSumItem, FactoryCustAgg } from '@/views/purchase-plan/components/types'

function facAgg(plan: number, produced: number): FactoryCustAgg {
  return {
    plan_qty: plan, inventory_qty: 0, produced_qty: produced,
    remaining_qty: plan - produced, warning_count: 0,
  }
}

const CUST: CustSumItem[] = [
  {
    customer_id: 1, customer_name: '客户甲', plan_qty: 150, inventory_qty: 0,
    produced_qty: 120, remaining_qty: 30, warning_count: 0,
    factories: {
      '东莞': facAgg(100, 100),
      '湖北': facAgg(50, 20),
    },
  },
]

// 三档配色：东莞 0% 红 / 湖北 40% 琥珀 / 未标注 100% 绿
const CUST_TONES: CustSumItem[] = [
  {
    customer_id: 1, customer_name: '客户甲', plan_qty: 300, inventory_qty: 0,
    produced_qty: 140, remaining_qty: 160, warning_count: 0,
    factories: {
      '东莞': facAgg(100, 0),
      '湖北': facAgg(100, 40),
      '未标注': facAgg(100, 100),
    },
  },
]

function mountCard(customers: CustSumItem[]) {
  return mount(FactorySummaryCard, { props: { customers } })
}

describe('FactorySummaryCard', () => {
  it('按 factories 渲染每厂一格 + 合计', () => {
    const w = mountCard(CUST)
    expect(w.findAll('.sp-fsum-cell')).toHaveLength(3)
    expect(w.findAll('.sp-fsum-plan').map(s => s.text())).toEqual(['100', '50', '150'])
    // 顺序：东莞 → 湖北 → 合计
    expect(w.findAll('.sp-fsum-name').map(s => s.text())).toEqual(['东莞', '湖北', '合计'])
    // 合计格带 sp-fsum-total
    expect(w.find('.sp-fsum-total').exists()).toBe(true)
  })

  it('完成率配色 0红/未满琥珀/满绿', () => {
    const w = mountCard(CUST_TONES)
    const bars = w.findAll('.sp-fsum-meter > i')
    // 东莞 0% 红 / 湖北 40% 琥珀 / 未标注 100% 绿 / 合计 46.6% 琥珀
    expect(bars[0]?.classes()).toContain('fm-r')
    expect(bars[1]?.classes()).toContain('fm-a')
    expect(bars[2]?.classes()).toContain('fm-g')
  })

  it('无 factories 时只有合计行', () => {
    const noFac: CustSumItem[] = [
      {
        customer_id: 1, customer_name: '客户甲', plan_qty: 150, inventory_qty: 0,
        produced_qty: 120, remaining_qty: 30, warning_count: 0,
      },
    ]
    const w = mountCard(noFac)
    expect(w.findAll('.sp-fsum-cell')).toHaveLength(1)
    expect(w.find('.sp-fsum-cell').classes()).toContain('sp-fsum-total')
  })
})
