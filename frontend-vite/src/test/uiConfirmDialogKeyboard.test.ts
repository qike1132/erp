/**
 * 删除确认框的键盘操作（2026-10-16）。
 *
 * 需求：确认框弹出后，用户按 Enter 直接触发「确认」，不必用鼠标点按钮；
 * Esc / 点遮罩外走「取消」。焦点落在输入框（如需要输入原因的确认框）时，
 * Enter 归输入框自己，不被抢。
 *
 * 实现点在统一渲染组件 UiConfirmDialog（全站删除确认框都过它），
 * 因此这一处行为变化 = 全站删除确认框一致生效。
 *
 * 测试方式：mount 真实组件，派发真实 keydown，断言 emit ——
 * 断言的是「用户按键 → 组件对外发出什么事件」这个真实行为，
 * 不是某个内部方法被调用过。
 */
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'

function mountDialog(props: Partial<InstanceType<typeof UiConfirmDialog>['$props']> = {}) {
  return mount(UiConfirmDialog, {
    props: { open: true, text: '确定删除明细「某产品」吗？', type: 'danger', ...props },
    attachTo: document.body,
  })
}

function keydown(key: string, target?: HTMLElement) {
  const el = target ?? document.activeElement ?? document.body
  el.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))
}

describe('UiConfirmDialog 键盘操作', () => {
  it('弹窗打开时按 Enter 触发确认', async () => {
    const wrapper = mountDialog()
    await wrapper.vm.$nextTick()

    // 焦点停在 document.body —— 输入框抢键分支不成立，Enter 应直达确认
    keydown('Enter', document.body)

    expect(wrapper.emitted('confirm')).toBeTruthy()
    expect(wrapper.emitted('confirm')?.length).toBe(1)
  })

  it('弹窗打开时按 Esc 触发取消', async () => {
    const wrapper = mountDialog()
    await wrapper.vm.$nextTick()

    keydown('Escape', document.body)

    expect(wrapper.emitted('cancel')).toBeTruthy()
  })

  it('焦点在输入框时按 Enter 不触发确认（交给输入框自己）', async () => {
    const wrapper = mountDialog()
    await wrapper.vm.$nextTick()

    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()

    keydown('Enter', input)

    expect(wrapper.emitted('confirm')).toBeFalsy()

    input.remove()
  })

  it('弹窗未打开时不监听 Enter（不 emit 任何事件）', async () => {
    const wrapper = mountDialog({ open: false })
    await wrapper.vm.$nextTick()

    keydown('Enter', document.body)

    expect(wrapper.emitted('confirm')).toBeFalsy()
    expect(wrapper.emitted('cancel')).toBeFalsy()
  })

  it('Enter 重复按下不会重复触发确认', async () => {
    const wrapper = mountDialog()
    await wrapper.vm.$nextTick()

    keydown('Enter', document.body)
    keydown('Enter', document.body)

    expect(wrapper.emitted('confirm')?.length).toBe(1)
  })
})
