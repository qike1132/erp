/**
 * M7 回归锁：UiAutocomplete 的早退分支必须让在途请求失效。
 *
 * 背景（2026-10-26 上线前检查 M7）
 * -------------------------------
 * `triggerSearch()` 在 `suppressSearch` 与 `q.length < minQueryLength` 两个分支
 * 提前 return，但**没有** `++requestSeq`：上一条请求回来时序号仍然匹配，于是把
 * 结果写进一个「已经清空/已被抑制」的下拉。短查询分支还不复位 loading，输入框
 * 的 spinner 会一直转到下一条响应为止。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { h } from 'vue'

vi.mock('primevue/autocomplete', () => ({
  default: {
    name: 'AutoComplete',
    props: ['suggestions', 'modelValue', 'optionLabel', 'placeholder', 'disabled',
            'inputId', 'loading', 'delay', 'minLength', 'appendTo',
            'showEmptyMessage', 'emptySearchMessage', 'pt'],
    emits: ['update:modelValue', 'complete', 'item-select', 'focus'],
    setup(props: Record<string, unknown>, { expose }: { expose: (o: object) => void }) {
      expose({ show: vi.fn(), hide: vi.fn() })
      return () => h('div', {
        class: 'ac-stub',
        'data-loading': String(props.loading),
      }, ((props.suggestions as { name: string }[]) ?? []).map(
        (s) => h('div', { class: 'ac-item' }, s.name)))
    },
  },
}))

import UiAutocomplete from '@/components/ui/UiAutocomplete.vue'

function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((r) => { resolve = r })
  return { promise, resolve }
}

function mountAc(props: Record<string, unknown>) {
  return mount(UiAutocomplete, { props })
}

describe('UiAutocomplete 早退分支（M7）', () => {
  beforeEach(() => vi.clearAllMocks())

  it('短查询早退必须作废在途请求并复位 loading', async () => {
    const pending = deferred<{ name: string }[]>()
    const searchFn = vi.fn(() => pending.promise)
    const wrapper = mountAc({ searchFn, minQueryLength: 3 })

    // 长查询：进入请求，loading=true
    wrapper.findComponent({ name: 'AutoComplete' }).vm.$emit('complete', { query: 'abcd' })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.ac-stub').attributes('data-loading')).toBe('true')

    // 退回到短查询：早退，必须停 loading 且作废旧请求
    wrapper.findComponent({ name: 'AutoComplete' }).vm.$emit('complete', { query: 'ab' })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.ac-stub').attributes('data-loading')).toBe('false')

    pending.resolve([{ name: '旧结果' }])
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()

    expect(wrapper.findAll('.ac-item')).toHaveLength(0)
  })

  it('suppress 分支早退同样作废在途请求', async () => {
    const pending = deferred<{ name: string }[]>()
    const searchFn = vi.fn(() => pending.promise)
    const wrapper = mountAc({ searchFn })

    wrapper.findComponent({ name: 'AutoComplete' }).vm.$emit('complete', { query: 'ab' })
    await wrapper.vm.$nextTick()

    ;(wrapper.vm as unknown as { setSuppressed: (v: boolean) => void }).setSuppressed(true)
    wrapper.findComponent({ name: 'AutoComplete' }).vm.$emit('complete', { query: 'abc' })
    await wrapper.vm.$nextTick()

    pending.resolve([{ name: '已提交前的旧结果' }])
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()

    expect(wrapper.findAll('.ac-item')).toHaveLength(0)
    expect(wrapper.find('.ac-stub').attributes('data-loading')).toBe('false')
  })

  it('正常远程搜索仍然写入结果并复位 loading（防过度收敛）', async () => {
    const searchFn = vi.fn(async () => [{ name: '产品A' }])
    const wrapper = mountAc({ searchFn })

    wrapper.findComponent({ name: 'AutoComplete' }).vm.$emit('complete', { query: 'a' })
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()

    expect(wrapper.findAll('.ac-item')).toHaveLength(1)
    expect(wrapper.find('.ac-stub').attributes('data-loading')).toBe('false')
  })
})
