/**
 * 移动端可交互元素的键盘可达性（2026-10-30 审计 A-M39）
 *
 * 现场：MListItem / MCard / MBadge 以及材料计算器的分类折叠头都是 div/span + @click，
 * 没有 role、没有 tabindex、没有键盘处理——外接键盘与读屏用户完全无法操作（域内
 * 标为严重）。修复后统一成 role=button + tabindex=0 + Enter/Space 等价点击，
 * 并给 :focus-visible 焦点环。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { mount } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({ pushMock: vi.fn() }))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mocks.pushMock }),
}))

import MListItem from '@/mobile/components/MListItem.vue'
import MCard from '@/mobile/components/MCard.vue'
import MBadge from '@/mobile/components/MBadge.vue'

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

describe('MCard 键盘可达', () => {
  it('clickable：Enter 发出 click 事件', async () => {
    const wrapper = mount(MCard, { props: { clickable: true } })
    const root = wrapper.find('.m-card')

    expect(root.attributes('role')).toBe('button')
    expect(root.attributes('tabindex')).toBe('0')

    await root.trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('click')).toHaveLength(1)
  })

  it('非 clickable：不可聚焦，也不发事件', async () => {
    const wrapper = mount(MCard, {})
    const root = wrapper.find('.m-card')

    expect(root.attributes('role')).toBeUndefined()
    await root.trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('click')).toBeUndefined()
  })
})

describe('MBadge 键盘可达', () => {
  it('interactive：Space 发出 click 事件', async () => {
    const wrapper = mount(MBadge, { props: { interactive: true }, slots: { default: '待审核' } })
    const root = wrapper.find('.m-badge')

    expect(root.attributes('role')).toBe('button')
    await root.trigger('keydown', { key: ' ' })
    expect(wrapper.emitted('click')).toHaveLength(1)
  })

  it('非 interactive：不可聚焦', () => {
    const wrapper = mount(MBadge, { slots: { default: '已通过' } })
    expect(wrapper.find('.m-badge').attributes('tabindex')).toBeUndefined()
  })
})

describe('材料计算器折叠头的键盘可达（结构锁）', () => {
  const src = readFileSync(
    resolve(process.cwd(), 'src/mobile/views/material-calculator/MMaterialCalculatorView.vue'),
    'utf-8',
  )

  it('三个折叠头都带 role/tabindex/aria-expanded/键盘处理', () => {
    const headers = src.match(/class="m-result-cat"[\s\S]{0,260}?@keydown="onCatKeydown/g) ?? []
    expect(headers).toHaveLength(3)
    expect(src.match(/class="m-result-cat"\s*\n\s*role="button"/g)).toHaveLength(3)
    expect(src.match(/aria-expanded=/g)?.length ?? 0).toBeGreaterThanOrEqual(3)
  })

  it('折叠头不再只有 @click（必须有键盘等价路径）', () => {
    expect(src).not.toMatch(/class="m-result-cat"\s+@click="toggle\(/)
  })
})
