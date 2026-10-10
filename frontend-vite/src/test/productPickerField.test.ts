/**
 * ProductPickerField —— 产品名称字段（整块可点）
 *
 * 从 OrderInputPanel 抽出来的纯展示组件：不认识搜索、不认识弹窗，只把点击转成事件。
 * 锁的行为：空态文案不能是空白（否则用户不知道这里要干什么）、有值时给清空入口。
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ProductPickerField from '@/views/customer-order/components/ProductPickerField.vue'

describe('ProductPickerField', () => {
  it('未选产品时显示引导文案，而不是留白', () => {
    const wrapper = mount(ProductPickerField, { props: { modelValue: '' } })
    expect(wrapper.find('.co-product-text').text()).toBe('点击选择产品')
    expect(wrapper.find('.co-product-field').classes()).toContain('co-product-field-empty')
  })

  it('已选产品时显示产品名，并给清空入口', async () => {
    const wrapper = mount(ProductPickerField, { props: { modelValue: '小熊毛绒玩具 20cm' } })
    expect(wrapper.find('.co-product-text').text()).toBe('小熊毛绒玩具 20cm')

    const clear = wrapper.find('.co-product-clear')
    expect(clear.exists()).toBe(true)
    await clear.trigger('click')
    expect(wrapper.emitted('clear')).toHaveLength(1)
    expect(wrapper.emitted('open')).toBeUndefined()
  })

  it('未选产品时不显示清空按钮（没有东西可清）', () => {
    const wrapper = mount(ProductPickerField, { props: { modelValue: '' } })
    expect(wrapper.find('.co-product-clear').exists()).toBe(false)
  })

  it('点击字段本身 emit open（不 emit clear）', async () => {
    const wrapper = mount(ProductPickerField, { props: { modelValue: '小熊' } })
    await wrapper.find('.co-product-field').trigger('click')
    expect(wrapper.emitted('open')).toHaveLength(1)
    expect(wrapper.emitted('clear')).toBeUndefined()
  })
})
