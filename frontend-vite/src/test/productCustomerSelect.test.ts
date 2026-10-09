/**
 * ProductCustomerSelect —— 产品「所属客户」多选控件
 *
 * 现有 UiSelect 是单选，产品归属是多对多，故单独做一个：已选项以 chips 展示，
 * 展开后是带搜索框的复选列表。
 *
 * 锁的行为：
 *   1. 勾选/取消都 emit 完整的新 id 数组（v-model 语义）；
 *   2. 未选任何客户时显示占位文案 —— 语义是「所有客户可见」，不是「谁都看不到」；
 *   3. 已选但不在选项里的客户 id 不能丢：保存时会把归属写空（等于放开给所有客户），
 *      这是静默的数据丢失，必须显示出来让用户看得见。
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ProductCustomerSelect from '@/views/product/components/ProductCustomerSelect.vue'

const OPTIONS = [
  { id: 1, name: '贝乐' },
  { id: 2, name: '海豚国际' },
  { id: 3, name: '星辉玩具' },
]

function mountSelect(modelValue: number[] = []) {
  return mount(ProductCustomerSelect, {
    props: { modelValue, options: OPTIONS, 'onUpdate:modelValue': () => {} },
  })
}

describe('ProductCustomerSelect', () => {
  it('勾选一个客户时 emit 包含它的新数组', async () => {
    const wrapper = mountSelect([])
    await wrapper.find('.pcs-field').trigger('click')
    await wrapper.findAll('.pcs-option')[0]!.trigger('click')

    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([[1]])
  })

  it('取消勾选时 emit 去掉它的新数组', async () => {
    const wrapper = mountSelect([1, 2])
    await wrapper.find('.pcs-field').trigger('click')
    await wrapper.findAll('.pcs-option')[1]!.trigger('click')

    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([[1]])
  })

  it('未选客户时显示「所有客户可见」的占位，而不是空白', () => {
    const wrapper = mountSelect([])
    expect(wrapper.find('.pcs-placeholder').text()).toContain('所有客户')
  })

  it('已选客户的 chip 会显示出来', () => {
    const wrapper = mountSelect([1, 2])
    const chips = wrapper.findAll('.pcs-chip').map((c) => c.text())
    expect(chips[0]).toContain('贝乐')
    expect(chips[1]).toContain('海豚国际')
  })

  it('已选但已不在选项里的客户 id 仍要显示，不能被静默丢掉', () => {
    // 客户被停用/删除后，产品的历史归属会指向不在 activeNames 里的 id
    const wrapper = mountSelect([99])
    expect(wrapper.findAll('.pcs-chip')).toHaveLength(1)
    expect(wrapper.find('.pcs-chip').text()).toContain('99')
  })

  it('搜索框按名称过滤选项', async () => {
    const wrapper = mountSelect([])
    await wrapper.find('.pcs-field').trigger('click')
    await wrapper.find('.pcs-search').setValue('海豚')

    const names = wrapper.findAll('.pcs-option-name').map((n) => n.text())
    expect(names).toEqual(['海豚国际'])
  })
})
