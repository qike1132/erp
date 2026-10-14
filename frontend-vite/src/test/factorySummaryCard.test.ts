/**
 * 「按工厂汇总」卡片（FactorySummaryCard）—— 覆盖：
 *   1. 渲染当前工厂一行：对 customers 顶层 plan_qty/produced_qty 求和；
 *   2. 完成率条按 0红/未满琥珀/满绿 上色；
 *   3. 空客户列表不除零。
 * 纯展示组件，mount 时不需要 PrimeVue。
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import FactorySummaryCard from '@/views/purchase-plan/components/FactorySummaryCard.vue'
import type { CustSumItem } from '@/views/purchase-plan/components/types'

function cust(plan: number, produced: number): CustSumItem {
  return {
    customer_id: 1, customer_name: '客户甲', plan_qty: plan, inventory_qty: 0,
    produced_qty: produced, remaining_qty: plan - produced, warning_count: 0,
  }
}

function mountCard(customers: CustSumItem[], factory = '东莞') {
  return mount(FactorySummaryCard, { props: { customers, factory } })
}

describe('FactorySummaryCard', () => {
  it('渲染当前工厂一行，汇总 customers 顶层 plan_qty/produced_qty', () => {
    const w = mountCard([cust(100, 100), cust(50, 20)])
    expect(w.findAll('.sp-fsum-cell')).toHaveLength(1)
    expect(w.find('.sp-fsum-name').text()).toBe('东莞')
    expect(w.find('.sp-fsum-plan').text()).toBe('150')
    expect(w.find('.sp-fsum-sub').text()).toContain('120')
    expect(w.find('.sp-fsum-pct').text()).toBe('80%')
  })

  it('完成率配色 0红/未满琥珀/满绿', () => {
    expect(mountCard([cust(100, 0)]).find('.sp-fsum-meter > i').classes()).toContain('fm-r')
    expect(mountCard([cust(100, 40)]).find('.sp-fsum-meter > i').classes()).toContain('fm-a')
    expect(mountCard([cust(100, 100)]).find('.sp-fsum-meter > i').classes()).toContain('fm-g')
  })

  it('工厂名作标题，色档跟随工厂', () => {
    const w = mountCard([cust(10, 5)], '湖北')
    expect(w.find('.sp-fsum-name').text()).toBe('湖北')
    expect(w.find('.sp-fsum-cell').attributes('data-tone')).toBe('hb')
  })

  it('空客户列表：计划量 0、完成率 0，不除零', () => {
    const w = mountCard([])
    expect(w.find('.sp-fsum-plan').text()).toBe('0')
    expect(w.find('.sp-fsum-pct').text()).toBe('0%')
  })
})
