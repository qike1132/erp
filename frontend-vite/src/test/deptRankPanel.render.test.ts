import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import DeptRankPanel from '@/views/production/components/DeptRankPanel.vue'
import type { DepartmentSummary } from '@/types'

function dept(department: string, label: string, qty: number): DepartmentSummary {
  return { department, department_label: label, total_quantity: qty, total_value: qty * 7, sku_count: 2 }
}

describe('DeptRankPanel', () => {
  it('按产量降序渲染，第一名在最上', () => {
    const wrapper = mount(DeptRankPanel, {
      props: {
        departments: [dept('filling', '充棉部', 100), dept('packaging', '包装部', 300), dept('handcraft', '手工部', 200)],
        loading: false,
      },
    })

    const rows = wrapper.findAll('[data-test="rank-row"]')
    expect(rows).toHaveLength(3)
    expect(rows[0]!.text()).toContain('包装部')
    expect(rows[1]!.text()).toContain('手工部')
    expect(rows[2]!.text()).toContain('充棉部')
  })

  it('受限用户只渲染返回的部门，不补三条', () => {
    // Review Focus #4
    const wrapper = mount(DeptRankPanel, {
      props: { departments: [dept('filling', '充棉部', 100)], loading: false },
    })

    expect(wrapper.findAll('[data-test="rank-row"]')).toHaveLength(1)
  })

  it('全部为 0 时渲染空态', () => {
    const wrapper = mount(DeptRankPanel, {
      props: { departments: [dept('filling', '充棉部', 0)], loading: false },
    })

    expect(wrapper.find('[data-test="rank-empty"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-test="rank-row"]')).toHaveLength(0)
  })

  it('加载中显示骨架', () => {
    const wrapper = mount(DeptRankPanel, { props: { departments: [], loading: true } })

    expect(wrapper.find('[data-test="rank-skeleton"]').exists()).toBe(true)
  })

  it('进度条宽度按"相对第一名的比例"给出，第一名占满', () => {
    const wrapper = mount(DeptRankPanel, {
      props: {
        departments: [dept('filling', '充棉部', 50), dept('packaging', '包装部', 200)],
        loading: false,
      },
    })

    const bars = wrapper.findAll('[data-test="rank-bar"]')
    expect(bars[0]!.attributes('style')).toContain('width: 100%')
    expect(bars[1]!.attributes('style')).toContain('width: 25%')
  })
})
