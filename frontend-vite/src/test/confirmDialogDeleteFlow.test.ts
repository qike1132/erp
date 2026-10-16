/**
 * 「打开确认框 → 按物理 Enter → 真的执行删除」这条完整链路的回归测试。
 *
 * 背景：全站删除确认统一走 useConfirmDialog（弹窗状态机）+ UiConfirmDialog
 * （唯一渲染出口，含 Enter=确认/Esc=取消键盘支持）。任何一处接线错误
 * （弹窗未绑 @confirm、或状态机 confirm() 没返回值）都会让回车确认失效。
 *
 * 这里刻意**不 mock** useConfirmDialog 与 UiConfirmDialog：用真实组合式函数 +
 * 真实组件，让 Enter 冒泡到 document 被组件捕获 → emit confirm → 回调触发
 * await 的删除动作。断言的是「按 Enter 后删除动作被执行」这个用户可见结果。
 *
 * 对照 Playwright 的真实浏览器实测等价物（jsdom 缺 keydown 焦点/焦点环细节）。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import { useConfirmDialog } from '@/composables/useConfirmDialog'

/**
 * 建一个「视图」宿主：持有 useConfirmDialog 状态 + 渲染真实 UiConfirmDialog，
 * 模拟页面结构（v-if + @confirm/@cancel 接线照抄各 view 的既有写法）。
 * 返回 dialog（供测试直接调 confirm 开弹窗）、包装器、以及执行计数。
 */
function mountHost() {
  let dialog!: ReturnType<typeof useConfirmDialog>
  const executed = vi.fn()
  const view = defineComponent({
    components: { UiConfirmDialog },
    setup() {
      dialog = useConfirmDialog()
      return { dialog }
    },
    render() {
      return h(UiConfirmDialog, {
        open: this.dialog.open,
        text: this.dialog.text,
        sub: this.dialog.sub,
        type: this.dialog.type,
        onConfirm: () => {
          this.dialog.onConfirm()
          void executed()
        },
        onCancel: () => this.dialog.onCancel(),
      })
    },
  })
  const wrapper = mount(view, { attachTo: document.body })
  return { wrapper, dialog, executed }
}

/** 模拟用户按下物理键（事件从 body 冒泡到 document，与真实浏览器一致） */
function pressKey(key: string) {
  document.body.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))
}

describe('删除确认框：回车确认完整链路', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('弹窗打开后按 Enter，删除动作被执行', async () => {
    const { wrapper, dialog, executed } = mountHost()

    // 用户点「删除」按钮 → confirm() 打开弹窗并返回 pending Promise
    const confirmPromise = dialog.confirm('确定删除备份文件「a.zip」？', '该操作不可恢复。')
    await wrapper.vm.$nextTick()
    expect(dialog.open).toBe(true)

    // 用户在弹窗前按下物理 Enter 键
    pressKey('Enter')
    await confirmPromise

    expect(executed).toHaveBeenCalledTimes(1)
    expect(dialog.open).toBe(false)
  })

  it('弹窗打开后按 Esc，删除动作不执行', async () => {
    const { wrapper, dialog, executed } = mountHost()

    const confirmPromise = dialog.confirm('确认删除「车缝」工序？')
    await wrapper.vm.$nextTick()

    pressKey('Escape')
    const ok = await confirmPromise

    expect(ok).toBe(false)
    expect(executed).not.toHaveBeenCalled()
    expect(dialog.open).toBe(false)
  })

  it('Enter 连按两次只执行一次删除（防重复触发）', async () => {
    const { wrapper, dialog, executed } = mountHost()

    const confirmPromise = dialog.confirm('确定删除备份文件「a.zip」？')
    await wrapper.vm.$nextTick()

    pressKey('Enter')
    pressKey('Enter') // 第一击已摘监听并关闭弹窗，第二击不应再生效
    await confirmPromise

    expect(executed).toHaveBeenCalledTimes(1)
  })

  it('焦点在输入框时按 Enter 不触发删除（Enter 归输入框）', async () => {
    const { wrapper, dialog, executed } = mountHost()

    const confirmPromise = dialog.confirm('删除需要输入原因的记录？')
    await wrapper.vm.$nextTick()

    // 模拟确认框从带输入框的表单里弹出、用户焦点停在输入框
    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }))

    const ok = await Promise.race([
      confirmPromise,
      new Promise<'pending'>((r) => setTimeout(() => r('pending'), 30)),
    ])

    expect(ok).toBe('pending') // 确认框仍开着，删除未执行
    expect(executed).not.toHaveBeenCalled()
    input.remove()
  })
})
