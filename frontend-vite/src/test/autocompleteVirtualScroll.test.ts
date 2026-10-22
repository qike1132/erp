import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import UiAutocomplete from '@/components/ui/UiAutocomplete.vue'

describe('UiAutocomplete', () => {
  it('passes virtualScrollerOptions to PrimeVue AutoComplete', () => {
    const wrapper = mount(UiAutocomplete, {
      props: { modelValue: '', suggestions: [] },
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
