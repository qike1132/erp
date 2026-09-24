import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'
import ProjectFormDialog from '../views/pattern-room/components/ProjectFormDialog.vue'
import type { ProjectDetailResponse } from '../api/patternRoom'

function makeFile(name = 'paste.png', type = 'image/png'): File {
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

/** 仅填充被弹窗读取的字段，其余用断言绕过完整形状要求 */
function projectDetail(): ProjectDetailResponse {
  return {
    id: 7,
    sequence_no: 'SP-0007',
    product_name: '小熊毛绒玩具',
    product_image_url: '/static/uploads/a.png',
    product_image_thumbnail_url: '/static/uploads/a_thumb.png',
    product_image_blur_url: null,
    product_image_file_id: 3,
    pattern_maker_id: null,
    pattern_maker_name: '',
    current_version: 'V1',
    status: 'in_progress',
    remark: '',
    created_by_name: null,
    created_at: '2026-09-24T10:00:00',
    updated_at: '2026-09-24T10:00:00',
    version: 1,
    parts: [],
    versions: [],
    roles: [],
  }
}

const wrappers: VueWrapper[] = []

/**
 * 以 visible=false 挂载后切到 true，与真实打开路径一致
 * （弹窗的数据装载依赖 visible 的 watch，而非初次挂载）
 */
async function mountDialog(project: ProjectDetailResponse | null, open = true) {
  const wrapper = mount(ProjectFormDialog, {
    props: {
      visible: false,
      project,
      patternMakers: [],
      patternMakerId: null,
      submitting: false,
    },
    attachTo: document.body,
  })
  wrappers.push(wrapper)
  if (open) {
    await wrapper.setProps({ visible: true })
    await flushPromises()
    await nextTick()
  }
  return wrapper
}

/** 取出粘贴热区并给出非零布局矩形（jsdom 无布局，需显式伪造） */
function hitZone(): HTMLElement {
  const zone = document.querySelector('.pjf-image-zone') as HTMLElement | null
  expect(zone).not.toBeNull()
  vi.spyOn(zone as HTMLElement, 'getBoundingClientRect').mockReturnValue({
    width: 400,
    height: 40,
    left: 10,
    top: 10,
    right: 410,
    bottom: 50,
    x: 10,
    y: 10,
    toJSON: () => ({}),
  } as DOMRect)
  return zone as HTMLElement
}

describe('打样项目弹窗图片粘贴接线', () => {
  beforeEach(() => {
    // jsdom 无布局能力：屏蔽 elementFromPoint，走「无遮挡检测」降级路径
    Object.defineProperty(document, 'elementFromPoint', { value: undefined, configurable: true })
    URL.createObjectURL = vi.fn(() => 'blob:mock-url') as unknown as typeof URL.createObjectURL
    URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL
  })

  afterEach(() => {
    while (wrappers.length) wrappers.pop()?.unmount()
    vi.restoreAllMocks()
  })

  it('已有产品图片时热区仍存在，粘贴后向父级抛出 upload-image', async () => {
    const wrapper = await mountDialog(projectDetail())
    // 已有图片 → 预览分支渲染，虚线框被替换（正是需要外层容器承载粘贴热区的原因）
    expect(document.querySelector('.diu-preview')).not.toBeNull()

    hitZone()
    document.dispatchEvent(pasteEvent(makeFile()))
    await flushPromises()

    const emitted = wrapper.emitted('upload-image')
    expect(emitted).toBeTruthy()
    expect(emitted).toHaveLength(1)
    expect(emitted![0]![0]).toBeInstanceOf(File)
  })

  it('新增态（无图片）粘贴后同样抛出 upload-image', async () => {
    const wrapper = await mountDialog(null)

    hitZone()
    document.dispatchEvent(pasteEvent(makeFile()))
    await flushPromises()

    expect(wrapper.emitted('upload-image')).toBeTruthy()
  })

  it('纯文本粘贴不触发图片上传', async () => {
    const wrapper = await mountDialog(projectDetail())

    hitZone()
    document.dispatchEvent(pasteEvent(null, 'hello'))
    await flushPromises()

    expect(wrapper.emitted('upload-image')).toBeFalsy()
  })

  it('弹窗关闭时不渲染热区，粘贴不会被吞掉', async () => {
    const wrapper = await mountDialog(projectDetail(), false)

    expect(document.querySelector('.pjf-image-zone')).toBeNull()
    document.dispatchEvent(pasteEvent(makeFile()))
    await flushPromises()

    expect(wrapper.emitted('upload-image')).toBeFalsy()
  })

  it('提交中（submitting）不响应粘贴', async () => {
    const wrapper = await mountDialog(projectDetail())
    await wrapper.setProps({ submitting: true })
    await nextTick()

    hitZone()
    document.dispatchEvent(pasteEvent(makeFile()))
    await flushPromises()

    expect(wrapper.emitted('upload-image')).toBeFalsy()
  })
})
