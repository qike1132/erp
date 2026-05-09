import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import UiButton from '@/components/ui/UiButton.vue'

describe('UiButton', () => {
  it('renders default button', () => {
    const wrapper = mount(UiButton, {
      slots: { default: 'Click me' },
    })
    expect(wrapper.text()).toContain('Click me')
    expect(wrapper.attributes('type')).toBe('button')
  })

  it('renders different variants', () => {
    const variants = ['primary', 'success', 'outline', 'ghost', 'danger'] as const
    for (const variant of variants) {
      const wrapper = mount(UiButton, {
        props: { variant },
        slots: { default: 'Btn' },
      })
      expect(wrapper.find('button').exists()).toBe(true)
    }
  })

  it('emits click event', async () => {
    const wrapper = mount(UiButton, {
      slots: { default: 'Click' },
    })
    await wrapper.find('button').trigger('click')
    expect(wrapper.emitted('click')).toBeTruthy()
  })
})
