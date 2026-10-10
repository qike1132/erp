/**
 * UiAutocomplete —— 「打开下拉即列全量」能力（2026-10-10）
 *
 * 场景：下单页的产品名称，点一下就要看到「该客户可见的全部 SKU」，打字再过滤。
 * 这是 PrimeVue AutoComplete 不带的：它只在输入后触发搜索，空关键字什么都不出。
 *
 * 关键约束：UiAutocomplete 被 6 个页面共用（出货/备货/皮套/湖北外发/BOM/OCR）。
 * 新能力必须**默认关闭** —— 没传 `listFn` 时行为一字不变，否则那 6 个页面会凭空
 * 在聚焦时弹出一个空下拉。
 *
 * 这里把 primevue 的 AutoComplete 换成最小桩：桩把 suggestions 渲染成 <li>，
 * 并在 focus/input 时按 PrimeVue 的语义 emit。`show()` 是"面板真的展开了"的唯一可断言信号，
 * 故桩把它暴露成 spy。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { h } from 'vue'

const showSpy = vi.hoisted(() => vi.fn())

vi.mock('primevue/autocomplete', () => ({
  default: {
    name: 'AutoComplete',
    props: ['suggestions', 'modelValue', 'optionLabel', 'placeholder', 'disabled',
            'inputId', 'loading', 'delay', 'minLength', 'appendTo',
            'showEmptyMessage', 'emptySearchMessage', 'pt'],
    emits: ['update:modelValue', 'complete', 'item-select', 'focus'],
    setup(props: Record<string, unknown>, { emit, expose }: { emit: (...a: unknown[]) => void; expose: (o: object) => void }) {
      expose({ show: showSpy, hide: vi.fn(), $el: null })
      return () => h('div', { class: 'ac-stub' }, [
        h('input', {
          class: 'ac-input',
          onFocus: () => emit('focus'),
          onInput: (e: Event) => emit('complete', { query: (e.target as HTMLInputElement).value }),
        }),
        h('ul', ((props.suggestions as { name: string }[]) ?? []).map(
          (s) => h('li', { class: 'ac-item' }, s.name))),
      ])
    },
  },
}))

import UiAutocomplete from '@/components/ui/UiAutocomplete.vue'

const LIST = [{ id: 1, name: '小熊毛绒玩具 20cm' }, { id: 2, name: '卡通抱枕 40×40' }]

function mountAc(props: Record<string, unknown>) {
  return mount(UiAutocomplete, { props })
}

describe('UiAutocomplete 打开下拉即列全量（listFn）', () => {
  beforeEach(() => showSpy.mockClear())

  it('聚焦且输入为空时调 listFn，并展开面板', async () => {
    const listFn = vi.fn(async () => [...LIST])
    const searchFn = vi.fn(async () => [])

    const wrapper = mountAc({ listFn, searchFn })
    await wrapper.find('.ac-input').trigger('focus')
    await flushPromises()

    expect(listFn).toHaveBeenCalledTimes(1)
    expect(searchFn).not.toHaveBeenCalled()
    expect(showSpy).toHaveBeenCalled()
    expect(wrapper.findAll('.ac-item').map((i) => i.text())).toEqual(['小熊毛绒玩具 20cm', '卡通抱枕 40×40'])
  })

  it('打字时走 searchFn，不走 listFn', async () => {
    const listFn = vi.fn(async () => [...LIST])
    const searchFn = vi.fn(async () => [{ id: 9, name: '独角兽挂件 8cm' }])

    const wrapper = mountAc({ listFn, searchFn })
    await wrapper.find('.ac-input').setValue('挂件')
    await flushPromises()

    expect(searchFn).toHaveBeenCalledWith('挂件')
    expect(listFn).not.toHaveBeenCalled()
    expect(wrapper.findAll('.ac-item').map((i) => i.text())).toEqual(['独角兽挂件 8cm'])
  })

  it('清空输入后回到全量列表', async () => {
    const listFn = vi.fn(async () => [...LIST])
    const searchFn = vi.fn(async () => [{ id: 9, name: '独角兽挂件 8cm' }])

    const wrapper = mountAc({ listFn, searchFn })
    await wrapper.find('.ac-input').setValue('挂件')
    await flushPromises()
    listFn.mockClear()

    await wrapper.find('.ac-input').setValue('')
    await flushPromises()

    expect(listFn).toHaveBeenCalledTimes(1)
    expect(wrapper.findAll('.ac-item')).toHaveLength(2)
  })

  it('没传 listFn 时聚焦什么都不做（其余 6 个页面零影响）', async () => {
    const searchFn = vi.fn(async () => [])

    const wrapper = mountAc({ searchFn })
    await wrapper.find('.ac-input').trigger('focus')
    await flushPromises()

    expect(searchFn).not.toHaveBeenCalled()
    expect(showSpy).not.toHaveBeenCalled()
    expect(wrapper.findAll('.ac-item')).toHaveLength(0)
  })

  it('listFn 返回空时照样展开面板（好让调用方给出「请先选择客户」这类文案）', async () => {
    const listFn = vi.fn(async () => [])

    const wrapper = mountAc({ listFn, emptyText: '请先选择客户' })
    await wrapper.find('.ac-input').trigger('focus')
    await flushPromises()

    expect(listFn).toHaveBeenCalledTimes(1)
    expect(showSpy).toHaveBeenCalled()
  })
})
