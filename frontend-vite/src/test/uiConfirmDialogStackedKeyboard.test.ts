/**
 * 多实例并存的键盘归属（2026-10-16 评审发现）。
 *
 * 缺陷：UiConfirmDialog 的 Enter/Esc 监听挂在 document 上，且不看「还有没有别的
 * 确认框开着」。DashboardView 同时挂两个（退出登录 + 备货提醒），备货提醒是
 * onMounted 里请求返回后才打开的 —— 湖北工厂用户在响应落地前点「退出登录」，
 * 会看到退出框、随后被备货框盖住。此时按一下 Enter，两个监听都触发：
 * 既登出又跳 /beile-order，路由互相抢，用户被送到备货页而不是登录页。
 *
 * 期望行为：同一时刻只有**最上层**那个确认框响应键盘，其余一律不响应 ——
 * 这与视觉层级一致（用户看到哪个框，按键就该作用到哪个框）。
 *
 * 测试方式：两个真实实例 + 真实 document keydown，断言 emit 归属。
 * 注意 open 必须由响应式状态驱动（真实视图里来自 ref/computed）；
 * 用普通 `{ value: true }` 对象改它不触发更新，watcher 不跑，测了个假场景。
 */
import { describe, it, expect, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h, reactive } from 'vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'

/** 一个宿主挂两个真实实例，模拟 DashboardView：先开 lower，再开 upper 盖在它之上 */
function mountStacked() {
  const emitted: Array<{ id: string; event: string }> = []
  function dialog(id: string, open: boolean) {
    return h(UiConfirmDialog, {
      open,
      text: `${id} 确认框`,
      type: 'danger',
      onConfirm: () => emitted.push({ id, event: 'confirm' }),
      onCancel: () => emitted.push({ id, event: 'cancel' }),
    })
  }
  const st = reactive({ lower: true, upper: false })
  const Host = defineComponent({
    setup: () => ({ st }),
    render() {
      return h('div', [dialog('lower', this.st.lower), dialog('upper', this.st.upper)])
    },
  })
  const wrapper = mount(Host, { attachTo: document.body })
  return { wrapper, st, emitted }
}

function pressKey(key: string) {
  document.body.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))
}

describe('UiConfirmDialog 多实例并存的键盘归属', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('上层后打开时，Enter 只触发最上层那个确认框', async () => {
    const { wrapper, st, emitted } = mountStacked()
    await wrapper.vm.$nextTick()

    st.upper = true // 备货提醒框后打开，盖在退出登录框之上
    await wrapper.vm.$nextTick()

    pressKey('Enter')

    expect(emitted).toEqual([{ id: 'upper', event: 'confirm' }])
  })

  it('上层后打开时，Esc 只关闭最上层那个确认框', async () => {
    const { wrapper, st, emitted } = mountStacked()
    await wrapper.vm.$nextTick()

    st.upper = true
    await wrapper.vm.$nextTick()

    pressKey('Escape')

    expect(emitted).toEqual([{ id: 'upper', event: 'cancel' }])
  })

  it('上层关闭后，Enter 回到下层那个确认框', async () => {
    const { wrapper, st, emitted } = mountStacked()
    await wrapper.vm.$nextTick()

    st.upper = true
    await wrapper.vm.$nextTick()
    pressKey('Escape') // 关掉上层
    await wrapper.vm.$nextTick()
    emitted.length = 0

    pressKey('Enter')

    expect(emitted).toEqual([{ id: 'lower', event: 'confirm' }])
  })

  it('只开一个时行为不变（单实例不受栈裁决影响）', async () => {
    const { wrapper, st, emitted } = mountStacked()
    await wrapper.vm.$nextTick()

    pressKey('Enter')

    expect(emitted).toEqual([{ id: 'lower', event: 'confirm' }])
    expect(st.lower).toBe(true)
  })
})
