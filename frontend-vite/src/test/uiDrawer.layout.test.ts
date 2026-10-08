/**
 * UiDrawer 的布局契约。
 *
 * 背景：PrimeVue 4.5 的 Drawer DOM 是三段式 ——
 *   mask（全屏 flex 容器，主题用 inline style 按 position 设 justify/align/z-index）
 *     └ root（面板本体）
 *         ├ header
 *         ├ content（内层滚动体）
 *         └ footer
 * primevue-pt.ts 曾按更老的 DOM 把「全屏容器」类挂到 root、把「面板」类挂到 content，
 * 后果：UiDrawer 的 width 落在 root（面板）上却被 content 的 w-[520px] 盖过，抽屉实测恒为
 * 520px，且 header 被 root 的 flex 行布局甩到屏幕左侧中部。
 *
 * 现有 RecordDrawer 渲染测试把 UiDrawer stub 掉了，这条契约此前无人覆盖，故在此钉住。
 */
import { afterEach, describe, expect, it } from 'vitest'
import { nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import PrimeVue from 'primevue/config'

import UiDrawer from '@/components/ui/UiDrawer.vue'
import { plushCutePT } from '@/styles/primevue-pt'

function mountDrawer(props: Record<string, unknown> = {}) {
  return mount(UiDrawer, {
    props: { visible: true, title: '标题', width: '960px', ...props },
    slots: { default: '<div data-test="body">BODY</div>' },
    attachTo: document.body,
    global: { plugins: [[PrimeVue, { unstyled: true, pt: plushCutePT }]] },
  })
}

const panel = () => document.querySelector<HTMLElement>('[data-pc-section="root"]')!
const content = () => document.querySelector<HTMLElement>('[data-pc-section="content"]')!
const header = () => document.querySelector<HTMLElement>('[data-pc-section="header"]')!

afterEach(() => {
  document.body.innerHTML = ''
})

describe('UiDrawer 布局契约', () => {
  it('宽度落在面板本体（inline style），而不是内层滚动体', async () => {
    mountDrawer({ width: '960px' })
    await nextTick()
    await nextTick()

    expect(panel().style.width).toBe('960px')
    // 面板必须是「面板」而非全屏容器 —— 否则 header 会被 flex 行布局甩到屏幕左侧
    expect(panel().classList.contains('fixed')).toBe(false)
    expect(panel().classList.contains('inset-0')).toBe(false)
    expect(panel().classList.contains('bg-white')).toBe(true)
  })

  it('内层 content 是滚动体，不承载面板外观', async () => {
    mountDrawer()
    await nextTick()
    await nextTick()

    expect(content().classList.contains('overflow-y-auto')).toBe(true)
    expect(content().classList.contains('flex-1')).toBe(true)
    // 面板外观（白底 + 520px 宽度）绝不能再出现在滚动体上 —— 那会盖过面板宽度
    expect(content().classList.contains('bg-white')).toBe(false)
    expect(content().classList.contains('w-[520px]')).toBe(false)
  })

  it('header 与 content 都挂在面板下（header 回到顶部）', async () => {
    mountDrawer()
    await nextTick()
    await nextTick()

    expect(panel().contains(header())).toBe(true)
    expect(panel().contains(content())).toBe(true)
  })

  it('上下抽屉不套用左右抽屉的 width（否则会被默认 520px 压窄）', async () => {
    mountDrawer({ position: 'bottom' })
    await nextTick()
    await nextTick()

    expect(panel().style.width).toBe('')
    expect(panel().classList.contains('w-full')).toBe(true)
  })

  it('居中模式：面板居中、固定尺寸，width 当作 max-width（而非固定宽度）', async () => {
    mountDrawer({ centered: true, width: '1100px' })
    await nextTick()
    await nextTick()

    // mask 用 flex 居中把面板摆到屏幕正中（主题对未知 position 的 inline style）
    const mask = document.querySelector<HTMLElement>('[data-pc-section="mask"]')!
    expect(mask.style.justifyContent).toBe('center')
    expect(mask.style.alignItems).toBe('center')

    expect(panel().style.maxWidth).toBe('1100px')
    expect(panel().style.width).toBe('')
    expect(panel().classList.contains('w-[95%]')).toBe(true)
    // 高度必须写死：行数少时面板不能跟着内容缩水
    expect(panel().classList.contains('h-[85vh]')).toBe(true)
    // 但也不能撑满高度，否则会变成整屏
    expect(panel().classList.contains('h-full')).toBe(false)
  })

  it('居中面板的内容区去掉顶部内边距（标题下沿不留一条空白）', async () => {
    mountDrawer({ centered: true })
    await nextTick()
    await nextTick()

    expect(content().classList.contains('pt-0')).toBe(true)
    expect(content().classList.contains('pt-5')).toBe(false)
  })

  it('左右抽屉的内容区保持顶部内边距（不受居中分支影响）', async () => {
    mountDrawer()
    await nextTick()
    await nextTick()

    expect(content().classList.contains('pt-5')).toBe(true)
  })

  it('dismissable 默认为 true：点遮罩空白会关闭', async () => {
    const wrapper = mountDrawer()
    await nextTick()
    await nextTick()

    document.querySelector<HTMLElement>('[data-pc-section="mask"]')!.dispatchEvent(
      new MouseEvent('mousedown', { bubbles: true }),
    )
    await nextTick()

    expect(wrapper.emitted('update:visible')).toEqual([[false]])
  })

  it('dismissable=false：点遮罩空白不关闭（只能用 ✕ / Esc）', async () => {
    const wrapper = mountDrawer({ dismissable: false })
    await nextTick()
    await nextTick()

    document.querySelector<HTMLElement>('[data-pc-section="mask"]')!.dispatchEvent(
      new MouseEvent('mousedown', { bubbles: true }),
    )
    await nextTick()

    expect(wrapper.emitted('update:visible')).toBeUndefined()
  })
})
