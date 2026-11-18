/**
 * 还原确认框必须是**真模态**（2026-10-17 审计 P1-19 / 报告内 FE-UI P1-1）。
 *
 * 原来它是手搓 `<div class="rw-overlay"><div class="rw-dialog">`：没有 role/aria-modal、
 * 没有焦点陷阱、没有 Esc、没有 body 滚动锁。打开瞬间焦点仍停在被点的「还原」按钮上，
 * 按一次 Tab 就落到同行的「下载」/「删除」——焦点在背景按钮上按回车**浏览器照常派发
 * click**（元素只是被 position:fixed 遮住，仍在 tab 序与可访问树里），于是「待确认的全库
 * 覆盖」期间还能再删一个备份文件；读屏器也完全不知道有模态弹窗。
 *
 * 改走共享 `UiDialog`（reka-ui DialogRoot + DialogContentModal）后，下面这些是库给的能力
 * 加上我们补的 `aria-modal`，本用例把它们钉住。注意内容经 `DialogPortal` 渲染到 body，
 * 断言走 `document` 查询而不是 wrapper。
 */
import { describe, it, expect } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'

import RestoreConfirmDialog from '@/components/backup/RestoreConfirmDialog.vue'
import UiDialog from '@/components/ui/UiDialog.vue'

/**
 * 生产里 `open` 是 false → true（点记录行「还原」），组件靠 `watch(open)` 初始化选中文件，
 * 所以这里也先以关闭态挂载再打开——直接以 open=true 挂载会绕过该 watch（selected 为空，
 * 「确认还原」按钮永远 disabled，测不到 running 态）。
 */
async function openDialog(overrides: Record<string, unknown> = {}) {
  const w = mount(RestoreConfirmDialog, {
    attachTo: document.body,
    props: {
      open: false,
      initialFilename: 'backup-2026-11-17.zip',
      plan: { success: true, table_count: 42, encrypted: true },
      planLoading: false,
      task: null,
      result: null,
      onPlan: () => {},
      onExecute: async () => true,
      ...overrides,
    },
  })
  await w.setProps({ open: true })
  await flushPromises()
  await nextTick()
  return w
}

function q<T extends Element>(selector: string): T {
  const el = document.querySelector<T>(selector)
  if (!el) throw new Error(`未找到 ${selector}`)
  return el
}

async function tick() {
  await flushPromises()
  await nextTick()
}

/** 勾选「已知晓」并点「确认还原」，把弹窗推进到 running 态 */
async function enterRunning() {
  const checkbox = q<HTMLInputElement>('.rw-overwrite-check input')
  checkbox.checked = true
  checkbox.dispatchEvent(new Event('change'))
  await tick()

  q<HTMLButtonElement>('.rw-btn-danger').click()
  await tick()
}

describe('P1-19 还原确认框：真模态契约', () => {
  it('打开时渲染 role="dialog" + aria-modal="true"（手搓 overlay 没有这两个属性）', async () => {
    const w = await openDialog()

    const dialog = q('[role="dialog"]')
    expect(dialog.getAttribute('aria-modal')).toBe('true')
    // 可访问名称来自 UiDialog 的 sr-only DialogTitle（srTitle）
    expect(dialog.textContent ?? '').toContain('还原备份')

    w.unmount()
  })

  it('打开后焦点被移进弹窗（旧实现焦点留在背景按钮上，Tab/Enter 可穿透）', async () => {
    const backgroundBtn = document.createElement('button')
    backgroundBtn.textContent = '删除'
    document.body.appendChild(backgroundBtn)
    backgroundBtn.focus()

    const w = await openDialog()

    const dialog = q('[role="dialog"]')
    expect(dialog.contains(document.activeElement)).toBe(true)
    expect(document.activeElement).not.toBe(backgroundBtn)

    w.unmount()
    backgroundBtn.remove()
  })

  it('表单态按 Esc → 请求关闭（旧实现完全没有 Esc 处理）', async () => {
    const w = await openDialog()

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await tick()

    expect(w.emitted('close')).toHaveLength(1)
    w.unmount()
  })

  it('执行中（running）按 Esc → 不关闭（还原不可中断）', async () => {
    const w = await openDialog()
    await enterRunning()
    expect(q('[role="dialog"]').textContent).toContain('正在执行还原')

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await tick()

    expect(w.emitted('close')).toBeUndefined()
    w.unmount()
  })

  it('执行中 ✕ / 取消按钮被禁用（只能等任务终态）', async () => {
    const w = await openDialog()
    await enterRunning()

    expect(q<HTMLButtonElement>('.rw-icon-btn').disabled).toBe(true)
    expect(q<HTMLButtonElement>('.rw-btn').disabled).toBe(true)

    w.unmount()
  })

  it('关闭请求统一走 onTryClose：UiDialog 报 open=false 时表单态关闭', async () => {
    const w = await openDialog()

    w.findComponent(UiDialog).vm.$emit('update:open', false)
    await tick()

    expect(w.emitted('close')).toHaveLength(1)
    w.unmount()
  })
})
