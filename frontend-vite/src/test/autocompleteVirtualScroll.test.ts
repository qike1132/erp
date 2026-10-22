import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import UiAutocomplete from '@/components/ui/UiAutocomplete.vue'

describe('UiAutocomplete', () => {
  it('passes virtualScrollerOptions for large suggestion lists', () => {
    const big = Array.from({ length: 100 }, (_, i) => ({ id: i, name: `n${i}` }))
    const wrapper = mount(UiAutocomplete, {
      props: { modelValue: '', suggestions: big, optionLabel: 'name' },
      global: {
        stubs: {
          AutoComplete: {
            name: 'AutoComplete',
            props: ['virtualScrollerOptions'],
            template: '<div class="ac-stub" />',
          },
        },
      },
    })
    const ac = wrapper.findComponent({ name: 'AutoComplete' })
    expect(ac.props('virtualScrollerOptions')).toMatchObject({
      itemSize: expect.any(Number),
    })
  })
})
