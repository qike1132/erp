/**
 * 回归：真实 PrimeVue 组件下，选中一项之后**不得**再把面板重新打开
 *
 * 用户两次报的是同一个 bug 的两副面孔：
 *   · 首报「选中后出现一个一模一样的名字」——重开时显示的是「拿选中值当关键字搜」的那一条
 *   · 再报「选中后列表该关闭却没关」——同一个重开，只是内容变成了全部列表
 *
 * 根因（实测证据）：`onFocus` 挂在 PrimeVue 的 `focus` 事件上，而**选中后 PrimeVue 会把焦点
 * 交回输入框**，于是 focus 再触发一次 → 面板重开。修法是把「打开」改挂输入框的原生 `click`
 * （真实用户手势；选中引起的是 focus，不是 click）。
 *
 * 这里用**真的**组件（不是桩）+ 与生产同款的 unstyled+PT 配置，硬证据是 `listFn` 的调用次数：
 * 面板有没有被重开，就是它有没有被多调一次。不靠断言面板 DOM —— jsdom 不跑过渡动画，
 * 离场元素会暂时留在树上，那个断言会假红。
 */
import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import PrimeVue from 'primevue/config'
import { plushCutePT } from '@/styles/primevue-pt'
import UiAutocomplete from '@/components/ui/UiAutocomplete.vue'

const LIST = [
  { id: 1, name: 'Mini Family外星系列毛绒公仔（土星墩）' },
  { id: 2, name: '3寸MINI FAMILY蒸包毛绒挂件（GIGI猪）' },
]

function mountReal() {
  const listFn = vi.fn(async () => [...LIST])
  const searchFn = vi.fn(async () => [...LIST])
  const wrapper = mount(UiAutocomplete, {
    props: { listFn, searchFn, appendTo: 'self', modelValue: '' },
    global: { plugins: [[PrimeVue, { unstyled: true, pt: plushCutePT }]] },
    attachTo: document.body,
  })
  return { wrapper, listFn, searchFn }
}

describe('UiAutocomplete（真实组件）选中后不重开面板', () => {
  it('点击展开 → 点选一项 → 不再拉取列表', async () => {
    const { wrapper, listFn } = mountReal()
    await flushPromises()

    // ① 点击输入框 → 展开并拉一次列表
    await wrapper.find('input').trigger('click')
    await flushPromises()
    expect(listFn).toHaveBeenCalledTimes(1)

    // ② 点选一项
    const options = wrapper.findAll('li[role="option"]')
    expect(options.length).toBeGreaterThan(0)
    await options[0]!.trigger('click')
    await flushPromises()
    expect(wrapper.emitted('update:modelValue')).toBeTruthy()

    // ③ 关键：选中后不该再拉列表（= 面板没被重开）
    expect(listFn).toHaveBeenCalledTimes(1)
  })

  it('选中之后再点一次输入框：应当重新列出全部（用户主动要求看列表）', async () => {
    const { wrapper, listFn } = mountReal()
    await flushPromises()

    await wrapper.find('input').trigger('click')
    await flushPromises()
    await wrapper.findAll('li[role="option"]')[0]!.trigger('click')
    await flushPromises()

    await wrapper.find('input').trigger('click')
    await flushPromises()

    expect(listFn).toHaveBeenCalledTimes(2)
  })
})
