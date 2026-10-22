import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { h } from 'vue'
import UiFormField, { type UiFormFieldControlProps } from '@/components/ui/UiFormField.vue'

/**
 * 表单字段标签范式回归（/pattern-room 审查 A11Y-04/05/18）。
 *
 * 核心契约：可见 <label> 的 for 必须等于控件 id，且 id 由组件自身保证唯一。
 * 这条一旦破了，读屏器就退化成读 placeholder —— 正是审查里 6 个标签全废的原因。
 */
function mountField(props: Record<string, unknown> = {}, control: 'input' | 'textarea' = 'input') {
  return mount(UiFormField, {
    props,
    slots: {
      // 用函数式插槽接收 fieldProps，模拟真实用法 v-bind="field"
      default: (field: UiFormFieldControlProps) => h(control, field),
    },
  })
}

describe('UiFormField 标签关联', () => {
  it('label 的 for 等于控件 id（关联成立）', () => {
    const w = mountField({ label: '产品名称' })
    const id = w.get('input').attributes('id')
    expect(id).toBeTruthy()
    expect(w.get('label').attributes('for')).toBe(id)
  })

  it('未传 label 时不渲染空 label 元素', () => {
    const w = mountField({})
    expect(w.find('label').exists()).toBe(false)
  })

  it('同页两个字段的 id 不冲突，且 label 各自指向自己的控件（不串台）', () => {
    /**
     * 必须在**同一个 app** 内挂两个字段才等价于真实页面。
     * useId() 的计数是按 app 实例走的：分两次 mount 会各自从 v-0 开始，
     * 那样测出来的"冲突"是测试假象，不是缺陷。
     */
    const w = mount(
      {
        render() {
          return h('div', [
            h(UiFormField, { label: 'A' }, { default: (f: UiFormFieldControlProps) => h('input', f) }),
            h(UiFormField, { label: 'B' }, { default: (f: UiFormFieldControlProps) => h('input', f) }),
          ])
        },
      },
      { attachTo: document.body },
    )

    const inputs = w.findAll('input')
    expect(inputs).toHaveLength(2)
    const ids = inputs.map((i) => i.attributes('id'))
    expect(ids[0]).not.toBe(ids[1])

    const labels = w.findAll('label')
    expect(labels).toHaveLength(2)
    expect(labels[0]!.attributes('for')).toBe(ids[0])
    expect(labels[1]!.attributes('for')).toBe(ids[1])
    expect(w.text()).toContain('A')
    expect(w.text()).toContain('B')
    w.unmount()
  })

  it('显式传入 id 时优先使用（用于对接后端字段名或跨组件引用）', () => {
    const w = mountField({ label: '备注', id: 'project-remark' })
    expect(w.get('input').attributes('id')).toBe('project-remark')
    expect(w.get('label').attributes('for')).toBe('project-remark')
  })

  it('textarea 同样可用（插槽透传与标签关联不绑定具体标签名）', () => {
    const w = mountField({ label: '备注' }, 'textarea')
    expect(w.get('label').attributes('for')).toBe(w.get('textarea').attributes('id'))
  })
})

describe('UiFormField 必填与校验', () => {
  it('required 同时产出原生 required 与 aria-required，并渲染 * 标记', () => {
    const w = mountField({ label: '产品名称', required: true })
    const input = w.get('input')
    expect(input.attributes('required')).toBeDefined()
    expect(input.attributes('aria-required')).toBe('true')
    expect(w.get('.ui-form-field__required').text()).toBe('*')
    // * 对读屏器隐藏，必填语义由 aria-required 承担，避免念"星号"
    expect(w.get('.ui-form-field__required').attributes('aria-hidden')).toBe('true')
  })

  it('非必填不产出 required / aria-required（保持缺省而非 false）', () => {
    const w = mountField({ label: '备注' })
    const input = w.get('input')
    expect(input.attributes('required')).toBeUndefined()
    expect(input.attributes('aria-required')).toBeUndefined()
  })

  it('error 触发 aria-invalid 与 role=alert', () => {
    const w = mountField({ label: '产品名称', error: '产品名称不能为空' })
    expect(w.get('input').attributes('aria-invalid')).toBe('true')
    expect(w.get('.ui-form-field__error').attributes('role')).toBe('alert')
    expect(w.text()).toContain('产品名称不能为空')
  })

  it('无错误时不设 aria-invalid（防止读屏器一直报"无效"）', () => {
    const w = mountField({ label: '产品名称' })
    expect(w.get('input').attributes('aria-invalid')).toBeUndefined()
  })
})

describe('UiFormField 说明文本关联', () => {
  it('hint 被 aria-describedby 引用，且 id 在 DOM 中真实存在', () => {
    const w = mountField({ label: '产品名称', hint: '不超过 200 字' })
    const describedBy = w.get('input').attributes('aria-describedby')
    expect(describedBy).toBeTruthy()
    expect(w.find(`#${describedBy}`).exists()).toBe(true)
    expect(w.find(`#${describedBy}`).text()).toBe('不超过 200 字')
  })

  it('hint 与 error 同时存在时两个 id 都进 aria-describedby', () => {
    const w = mountField({ label: '产品名称', hint: '不超过 200 字', error: '格式错误' })
    const ids = (w.get('input').attributes('aria-describedby') ?? '').split(' ')
    expect(ids).toHaveLength(2)
    for (const id of ids) {
      expect(w.find(`#${id}`).exists()).toBe(true)
    }
  })

  it('空字符串的 hint/error 不产生悬空 id 引用', () => {
    const w = mountField({ label: '产品名称', hint: '', error: '' })
    expect(w.get('input').attributes('aria-describedby')).toBeUndefined()
  })

  it('无线索文本时不设 aria-describedby', () => {
    const w = mountField({ label: '产品名称' })
    expect(w.get('input').attributes('aria-describedby')).toBeUndefined()
  })
})
