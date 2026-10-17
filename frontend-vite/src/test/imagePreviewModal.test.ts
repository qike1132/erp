/**
 * ImagePreviewModal 迁移到共享 UiDialog 后的键盘 / 遮罩行为回归测试（2026-10-16）。
 *
 * 背景：原实现是手写 Teleport 全屏遮罩，关闭只有 ✕ 一条路径，无任何键盘监听
 * → 无法用 Esc 关闭。迁移到 UiDialog 后复用其 Esc / 焦点陷阱 / 滚动锁。
 *
 * 本测试挂载**真实** UiDialog（reka-ui Dialog），走完整事件链：
 *   - Esc: DismissableLayer `onKeyStroke('Escape')` → escapeKeyDown → dismiss
 *          → DialogRoot update:open(false) → ImagePreviewModal.onOpenChange → emit update:image(null)
 *   - 点遮罩空白: pointerdown(外侧) → interactOutside → UiDialog.onInteractOutside
 *          → (closeOnOverlayClick=false 则 preventDefault) → 不关闭
 * 反向对照守住「点遮罩空白不关闭」这条全站约定（2026-10-14）。
 */
import { describe, it, expect } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import ImagePreviewModal from '@/components/ui/ImagePreviewModal.vue'

/**
 * reka-ui DismissableLayer 在 window.setTimeout(0) 后才挂上监听；事件回调又在
 * nextTick 后决定是否 dismiss。用真实宏任务 + 微任务让「监听就绪 / 决策完成」都发生。
 */
async function settle() {
  await new Promise((resolve) => setTimeout(resolve, 0))
  await flushPromises()
  await nextTick()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await flushPromises()
  await nextTick()
}

function mountModal(image: string | null = 'uploads/products/test.png') {
  return mount(ImagePreviewModal, {
    props: { image },
    attachTo: document.body,
  })
}

/** 派发一次 Esc（冒泡到 window，命中 reka-ui 的 onKeyStroke('Escape')） */
function pressEscape() {
  document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
}

/** 在弹窗之外的 document.body 上派发一次可取消的 pointerdown（模拟点击遮罩外侧空白） */
function pointerDownOutside() {
  document.body.dispatchEvent(new Event('pointerdown', { bubbles: true, cancelable: true }))
}

describe('ImagePreviewModal 迁移 UiDialog 后的行为', () => {
  it('image 非空时渲染对话框（image → open 适配正确）', async () => {
    const wrapper = mountModal()
    await settle()

    expect(document.querySelector('.pim-card')).toBeTruthy()

    wrapper.unmount()
  })

  it('【核心】按 Esc 关闭并 emit update:image(null)', async () => {
    const wrapper = mountModal()
    await settle()

    pressEscape()
    await settle()

    const emitted = wrapper.emitted('update:image')
    expect(emitted).toBeTruthy()
    expect(emitted![0]![0]).toBeNull()

    wrapper.unmount()
  })

  it('【守住约定】点遮罩空白不关闭，不 emit update:image', async () => {
    const wrapper = mountModal()
    await settle()

    pointerDownOutside()
    await settle()

    expect(wrapper.emitted('update:image')).toBeFalsy()

    wrapper.unmount()
  })

  it('image 为 null 时不渲染对话框', async () => {
    const wrapper = mountModal(null)
    await settle()

    expect(document.querySelector('.pim-card')).toBeFalsy()

    wrapper.unmount()
  })
})
