import { describe, it, expect } from 'vitest'
import { ref, computed } from 'vue'
import { useSelectionA11y, selectionItemAttrs } from '@/composables/useSelectionA11y'

/**
 * 选中态范式回归（/pattern-room 审查 A11Y-06/07）。
 *
 * 这组测试守护的核心契约不是「能返回 true/false」，而是：
 *   aria-pressed **属性必须始终存在**，且值必须是字符串。
 * 因为「属性缺省」在 ARIA 语义里等于「这不是切换按钮」，
 * 与「是切换按钮但未按下」是两件事 —— 一旦哪天有人把返回值改成 boolean
 * 或在 attrs 合并时丢了 false，读屏器语义就静默降级了。
 */
describe('selectionItemAttrs', () => {
  it('选中返回字符串 "true"，未选中返回字符串 "false"', () => {
    expect(selectionItemAttrs(true)).toEqual({ 'aria-pressed': 'true' })
    expect(selectionItemAttrs(false)).toEqual({ 'aria-pressed': 'false' })
  })

  it('未选中时属性仍然存在（不能因 false 而被省略）', () => {
    const attrs = selectionItemAttrs(false)
    expect('aria-pressed' in attrs).toBe(true)
    expect(typeof attrs['aria-pressed']).toBe('string')
  })
})

describe('useSelectionA11y', () => {
  it('按当前值判定选中，切换后翻转', () => {
    const active = ref<'in_progress' | 'completed'>('in_progress')
    const { itemAttrs, isActive } = useSelectionA11y(() => active.value)

    expect(itemAttrs('in_progress')['aria-pressed']).toBe('true')
    expect(itemAttrs('completed')['aria-pressed']).toBe('false')

    active.value = 'completed'

    expect(itemAttrs('in_progress')['aria-pressed']).toBe('false')
    expect(itemAttrs('completed')['aria-pressed']).toBe('true')
    expect(isActive('completed')).toBe(true)
  })

  it('接受 ref 直接作为入参（toValue 路径）', () => {
    const active = ref(2)
    const { itemAttrs } = useSelectionA11y(active)
    expect(itemAttrs(2)['aria-pressed']).toBe('true')
    expect(itemAttrs(3)['aria-pressed']).toBe('false')
  })

  it('绑定 computed 时同样响应', () => {
    const raw = ref(1)
    const { itemAttrs } = useSelectionA11y(computed(() => raw.value))
    expect(itemAttrs(1)['aria-pressed']).toBe('true')
    raw.value = 2
    expect(itemAttrs(1)['aria-pressed']).toBe('false')
  })

  it('未选中任何值（null）时所有选项均为 "false"，不会抛错', () => {
    const { itemAttrs } = useSelectionA11y(() => null as number | null)
    expect(itemAttrs(1)['aria-pressed']).toBe('false')
    expect(itemAttrs(0)['aria-pressed']).toBe('false')
  })

  it('自定义比较函数：对象按 id 比较', () => {
    interface Role {
      id: number
    }
    const current = ref<Role | null>({ id: 7 })
    const { itemAttrs } = useSelectionA11y(
      () => current.value,
      (active, candidate) => active?.id === candidate.id,
    )
    expect(itemAttrs({ id: 7 })['aria-pressed']).toBe('true')
    expect(itemAttrs({ id: 8 })['aria-pressed']).toBe('false')
  })

  it('变异检查锚点：把判定逻辑反转，本组用例必须变红', () => {
    // 正常情况下「选中项的邻居」一定是 false。
    // 若实现被写成 itemAttrs 恒返回 'true'（例如漏了三元分支），此处会失败。
    const { itemAttrs } = useSelectionA11y(() => 'a')
    const notSelected = itemAttrs('b')
    expect(notSelected['aria-pressed']).toBe('false')
    expect(itemAttrs('a')['aria-pressed']).not.toBe(notSelected['aria-pressed'])
  })
})
