import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import UiLoadingStatus from '@/components/ui/UiLoadingStatus.vue'

/**
 * 加载态播报范式回归（/pattern-room 审查 A11Y-13）。
 *
 * 三条硬契约：
 *   1. 容器常驻 DOM —— 用 v-if 控制容器会让「首次出现即填充」的路径丢播报；
 *   2. role="status" + aria-live="polite" 必须同时存在；
 *   3. live region 自身**不得**带 aria-busy —— 部分实现会因此推迟播报，
 *      等于把「加载中」这句话吞掉（这是本组件最容易被人"顺手优化"错的地方）。
 */
function mountStatus(props: Record<string, unknown> = {}) {
  return mount(UiLoadingStatus, { props: { loading: false, ...props } })
}

describe('UiLoadingStatus', () => {
  it('空闲态节点仍然存在（防止有人改回 v-if 控制容器）', () => {
    const w = mountStatus()
    expect(w.find('[role="status"]').exists()).toBe(true)
    // 存在 but 不占视觉空间
    expect(w.classes()).toContain('is-idle')
  })

  it('role=status 与 aria-live=polite 同时存在', () => {
    const w = mountStatus()
    const region = w.get('[role="status"]')
    expect(region.attributes('aria-live')).toBe('polite')
    expect(region.attributes('aria-atomic')).toBe('true')
  })

  it('live region 自身不带 aria-busy', () => {
    const w = mountStatus({ loading: true })
    expect(w.get('[role="status"]').attributes('aria-busy')).toBeUndefined()
  })

  it('loading 变 true 时渲染文案，且退出空闲样式', async () => {
    const w = mountStatus({ label: '加载部位数据…' })
    expect(w.text()).not.toContain('加载部位数据')

    await w.setProps({ loading: true })

    expect(w.text()).toContain('加载部位数据')
    expect(w.classes()).not.toContain('is-idle')
  })

  it('loading 回到 false 后文案清空，避免残留播报', async () => {
    const w = mountStatus({ loading: true, label: '加载中…' })
    expect(w.text()).toContain('加载中')

    await w.setProps({ loading: false })

    expect(w.text()).toBe('')
    expect(w.classes()).toContain('is-idle')
  })

  it('doneLabel 在完成后播报（节点仍带 is-idle，视觉不留白）', async () => {
    const w = mountStatus({ loading: true, doneLabel: '加载完成' })
    await w.setProps({ loading: false })

    expect(w.text()).toContain('加载完成')
    expect(w.classes()).toContain('is-idle')
  })

  it('默认插槽可覆盖文案（带变量文案场景）', () => {
    const w = mount(UiLoadingStatus, {
      props: { loading: true },
      slots: { default: '正在加载 12 条记录' },
    })
    expect(w.text()).toContain('正在加载 12 条记录')
  })

  it('指示器对读屏器隐藏，只播报文字', () => {
    const w = mountStatus({ loading: true })
    const mark = w.get('.ui-loading-status__mark')
    expect(mark.attributes('aria-hidden')).toBe('true')
  })

  it('size 切换只影响视觉，不影响语义', async () => {
    const w = mountStatus({ loading: true, size: 'md' })
    expect(w.get('.ui-loading-status__mark').classes()).toContain('ui-loading-status__mark--md')
    await w.setProps({ size: 'sm' })
    expect(w.get('.ui-loading-status__mark').classes()).toContain('ui-loading-status__mark--sm')
  })
})
