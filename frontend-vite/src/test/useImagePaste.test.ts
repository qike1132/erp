import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, ref, type Ref } from 'vue'
import { useImagePaste } from '../composables/useImagePaste'

function makeFile(name = 'image.png', type = 'image/png'): File {
  return new File([new Uint8Array([1, 2, 3])], name, { type })
}

/** 模拟剪贴板事件：file 为 null 时表示纯文本粘贴 */
function pasteEvent(file: File | null, text = ''): ClipboardEvent {
  const dataTransfer = {
    items: file ? [{ kind: 'file', type: file.type, getAsFile: () => file }] : [],
    files: file ? [file] : [],
    getData: () => text,
  }
  const event = new Event('paste', { bubbles: true, cancelable: true }) as ClipboardEvent
  Object.defineProperty(event, 'clipboardData', { value: dataTransfer })
  return event
}

const mounted: VueWrapper[] = []

/**
 * 挂载一个「粘贴上传区」宿主组件，返回命中记录与元素引用。
 * rect=null 表示元素不可见（宽高为 0）。
 */
function mountZone(options: { enabled?: () => boolean; priority?: number; visible?: boolean } = {}) {
  const hits: File[] = []
  const el = ref<HTMLElement | null>(null)
  const Host = defineComponent({
    setup() {
      useImagePaste({
        target: el as Ref<HTMLElement | null>,
        onFile: (file) => hits.push(file),
        enabled: options.enabled,
        priority: options.priority,
      })
      return { el }
    },
    template: '<div ref="el" class="zone" />',
  })
  const wrapper = mount(Host, { attachTo: document.body })
  mounted.push(wrapper)

  const node = wrapper.element as HTMLElement
  vi.spyOn(node, 'getBoundingClientRect').mockReturnValue({
    width: options.visible === false ? 0 : 200,
    height: options.visible === false ? 0 : 40,
    left: 10,
    top: 10,
    right: 210,
    bottom: 50,
    x: 10,
    y: 10,
    toJSON: () => ({}),
  } as DOMRect)

  return { hits, node, wrapper }
}

describe('产品图片粘贴上传（useImagePaste）', () => {
  beforeEach(() => {
    // jsdom 无布局能力：屏蔽 elementFromPoint，走「无遮挡检测」降级路径
    Object.defineProperty(document, 'elementFromPoint', { value: undefined, configurable: true })
  })

  afterEach(() => {
    while (mounted.length) mounted.pop()?.unmount()
    vi.restoreAllMocks()
  })

  it('剪贴板含图片时命中回调并阻止默认行为', () => {
    const { hits } = mountZone()
    const file = makeFile()
    const event = pasteEvent(file)
    document.dispatchEvent(event)

    expect(hits).toEqual([file])
    expect(event.defaultPrevented).toBe(true)
  })

  it('纯文本粘贴不拦截，也不触发上传', () => {
    const { hits } = mountZone()
    const event = pasteEvent(null, 'hello')
    document.dispatchEvent(event)

    expect(hits).toHaveLength(0)
    expect(event.defaultPrevented).toBe(false)
  })

  it('粘贴区不可见时不响应', () => {
    const { hits } = mountZone({ visible: false })
    document.dispatchEvent(pasteEvent(makeFile()))
    expect(hits).toHaveLength(0)
  })

  it('enabled 为 false 时不响应（例如弹窗关闭、表单提交中）', () => {
    const { hits } = mountZone({ enabled: () => false })
    document.dispatchEvent(pasteEvent(makeFile()))
    expect(hits).toHaveLength(0)
  })

  it('多实例仲裁：优先级高者胜出，低优先级不重复上传', () => {
    const form = mountZone({ priority: 0 })
    const dialog = mountZone({ priority: 10, enabled: () => true })
    document.dispatchEvent(pasteEvent(makeFile()))

    expect(dialog.hits).toHaveLength(1)
    expect(form.hits).toHaveLength(0)
  })

  it('高优先级实例不可用时回落到低优先级', () => {
    const form = mountZone({ priority: 0 })
    const dialog = mountZone({ priority: 10, enabled: () => false })
    document.dispatchEvent(pasteEvent(makeFile()))

    expect(dialog.hits).toHaveLength(0)
    expect(form.hits).toHaveLength(1)
  })

  it('只有一个实例时只上传一次（不重复触发）', () => {
    const { hits } = mountZone()
    document.dispatchEvent(pasteEvent(makeFile()))
    expect(hits).toHaveLength(1)
  })

  it('组件卸载后不再响应粘贴', () => {
    const { hits, wrapper } = mountZone()
    wrapper.unmount()
    mounted.pop()
    document.dispatchEvent(pasteEvent(makeFile()))
    expect(hits).toHaveLength(0)
  })
})
