/**
 * 移动端可交互元素的键盘可达性（2026-10-30 审计 A-M39）
 *
 * 现场：MListItem 等移动端交互元素是 div/span + @click，没有 role、没有
 * tabindex、没有键盘处理——外接键盘与读屏用户完全无法操作（域内标为严重）。
 * 修复后统一成 role=button + tabindex=0 + Enter/Space 等价点击，并给
 * :focus-visible 焦点环。
 *
 * 2026-11-23：移动端收敛为「概览 / 登录 / 我的」，MCard / MBadge / 材料计算器
 * 已随页面删除；本文件只保留仍在用的 MListItem 部分。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({ pushMock: vi.fn() }))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mocks.pushMock }),
}))

import MListItem from '@/mobile/components/MListItem.vue'

describe('MListItem 键盘可达', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('有跳转目标：role=button + tabindex=0，Enter 触发跳转', async () => {
    const wrapper = mount(MListItem, { props: { title: '订单', to: '/orders' } })
    const root = wrapper.find('.m-list-item')

    expect(root.attributes('role')).toBe('button')
    expect(root.attributes('tabindex')).toBe('0')

    await root.trigger('keydown', { key: 'Enter' })
    expect(mocks.pushMock).toHaveBeenCalledWith('/orders')
  })

  it('Space 等同于点击（且阻止页面滚动）', async () => {
    const wrapper = mount(MListItem, { props: { title: '订单', to: '/orders' } })
    const root = wrapper.find('.m-list-item')

    const evt = new KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true })
    root.element.dispatchEvent(evt)

    expect(mocks.pushMock).toHaveBeenCalledWith('/orders')
    expect(evt.defaultPrevented).toBe(true)
  })

  it('clickable（无跳转）时仍可键盘触发外部 click 监听', async () => {
    const onClick = vi.fn()
    const wrapper = mount(MListItem, {
      props: { title: '退出登录', clickable: true },
      attrs: { onClick },
    })
    const root = wrapper.find('.m-list-item')

    expect(root.attributes('role')).toBe('button')
    await root.trigger('keydown', { key: 'Enter' })
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('纯展示项不进入 Tab 序列', () => {
    const wrapper = mount(MListItem, { props: { title: '只读信息' } })
    const root = wrapper.find('.m-list-item')

    expect(root.attributes('role')).toBeUndefined()
    expect(root.attributes('tabindex')).toBeUndefined()
  })
})