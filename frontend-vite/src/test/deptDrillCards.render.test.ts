import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import DeptDrillCards from '@/views/production/components/DeptDrillCards.vue'
import type { DepartmentSummary } from '@/types'

function dept(department: string, label: string, qty: number, value: number): DepartmentSummary {
  return { department, department_label: label, total_quantity: qty, total_value: value, sku_count: 2 }
}

const three = [
  dept('filling', '充棉部', 1240, 8680),
  dept('handcraft', '手工部', 860, 12040),
  dept('packaging', '包装部', 2150, 6450),
]

describe('DeptDrillCards', () => {
  it('渲染后端返回的每个部门，显示件数与产值', () => {
    const wrapper = mount(DeptDrillCards, { props: { departments: three, loading: false } })

    expect(wrapper.findAll('[data-test="dept-card"]')).toHaveLength(3)
    expect(wrapper.text()).toContain('充棉部')
    expect(wrapper.text()).toContain('1,240')
  })

  it('点击卡片 emit drill 并带上部门键（不是中文名）', async () => {
    const wrapper = mount(DeptDrillCards, { props: { departments: three, loading: false } })

    await wrapper.findAll('[data-test="dept-card"]')[2]!.trigger('click')

    expect(wrapper.emitted('drill')).toEqual([['packaging']])
  })

  it('受限用户只有一张卡时不补满三张', () => {
    // Review Focus #4
    const wrapper = mount(DeptDrillCards, { props: { departments: [three[0]!], loading: false } })

    expect(wrapper.findAll('[data-test="dept-card"]')).toHaveLength(1)
  })

  it('加载中显示骨架', () => {
    const wrapper = mount(DeptDrillCards, { props: { departments: [], loading: true } })

    expect(wrapper.find('[data-test="dept-skeleton"]').exists()).toBe(true)
  })

  it('无可见部门时渲染空态', () => {
    const wrapper = mount(DeptDrillCards, { props: { departments: [], loading: false } })

    expect(wrapper.find('[data-test="dept-empty"]').exists()).toBe(true)
  })
})
