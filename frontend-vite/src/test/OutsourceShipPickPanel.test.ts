/**
 * OutsourceShipPickPanel 左栏子组件测试
 *
 * 纯展示 + 事件上抛：卡片点击/勾选 = toggle、全选 = select-all；
 * 过滤在组件内按 v-model:keyword 进行；选中态由 selectedNames prop 驱动。
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import OutsourceShipPickPanel from '@/views/outsource/components/OutsourceShipPickPanel.vue'
import type { PickGroup } from '@/views/outsource/components/shipCartModel'

function group(over: Partial<PickGroup> = {}): PickGroup {
  return {
    key: over.productName ?? 'SKU-A', productName: over.productName ?? 'SKU-A',
    orderIds: over.orderIds ?? [1], orderCount: over.orderIds?.length ?? 1,
    ...over,
  }
}

function mountPanel(props: Partial<{ groups: PickGroup[]; selectedNames: string[]; keyword: string }> = {}) {
  return mount(OutsourceShipPickPanel, {
    props: {
      groups: props.groups ?? [group()],
      selectedNames: props.selectedNames ?? [],
      keyword: props.keyword ?? '',
    },
    global: {
      stubs: { FontAwesomeIcon: { template: '<i />' } },
    },
  })
}

describe('OutsourceShipPickPanel 左栏挑选', () => {
  it('渲染挑选项：产品名 + 计数；单订单无角标', () => {
    const wrapper = mountPanel({ groups: [group(), group({ key: 'SKU-B', productName: 'SKU-B' })] })
    expect(wrapper.findAll('.osw-card').length).toBe(2)
    expect(wrapper.find('.osw-l-meta').text()).toContain('待发货产品 2 项')
    expect(wrapper.findAll('.osw-prod-orders').length).toBe(0)
  })

  it('跨订单产品显示「N单」角标', () => {
    const wrapper = mountPanel({ groups: [group({ orderIds: [1, 2], orderCount: 2 })] })
    expect(wrapper.find('.osw-prod-orders').text()).toBe('2单')
  })

  it('点击卡片触发 toggle，payload 为对应 PickGroup；复选框点击同样触发', async () => {
    const g = group()
    const wrapper = mountPanel({ groups: [g] })
    await wrapper.find('.osw-card').trigger('click')
    expect(wrapper.emitted('toggle')![0]).toEqual([g])
    await wrapper.find('input.osw-cbx').trigger('click')
    expect(wrapper.emitted('toggle')![1]).toEqual([g])
  })

  it('selectedNames 命中时卡片带 is-on 且复选框选中', () => {
    const wrapper = mountPanel({ selectedNames: ['SKU-A'] })
    expect(wrapper.find('.osw-card').classes()).toContain('is-on')
    expect((wrapper.find('input.osw-cbx').element as HTMLInputElement).checked).toBe(true)
  })

  it('关键字过滤列表与计数；无匹配显示空态', async () => {
    const wrapper = mountPanel({
      groups: [group(), group({ key: 'SKU-B', productName: 'SKU-B' })],
    })
    await wrapper.find('.osw-search input').setValue('SKU-B')
    expect(wrapper.findAll('.osw-card').length).toBe(1)
    expect(wrapper.find('.osw-l-meta').text()).toContain('待发货产品 1 项')
    await wrapper.find('.osw-search input').setValue('不存在')
    expect(wrapper.findAll('.osw-card').length).toBe(0)
    expect(wrapper.find('.osw-l-empty').text()).toBe('没有匹配的产品')
  })

  it('点击全选触发 select-all（过滤由父组件按同关键字执行）', async () => {
    const wrapper = mountPanel()
    await wrapper.find('.osw-l-meta .osw-link').trigger('click')
    expect(wrapper.emitted('select-all')).toHaveLength(1)
  })

  it('表头只展示「产品名称」列', () => {
    const wrapper = mountPanel()
    expect(wrapper.find('.osw-l-head-prod').text()).toBe('产品名称')
  })
})
