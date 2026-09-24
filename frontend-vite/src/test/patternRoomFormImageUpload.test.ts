import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent } from 'vue'

// hoisted：保证 mock 变量先于 vi.mock 工厂初始化
const { showToast } = vi.hoisted(() => ({
  showToast: vi.fn((_message: string, _type?: string) => undefined),
}))

vi.mock('@/composables/useToast', () => ({ showToast }))

import { useFormImageUpload } from '../views/pattern-room/composables/useFormImageUpload'

/** 构造一个 File；content 用最小合法字节即可，size 不参与构造 */
function makeFile(name: string, type: string, bytes = [1, 2, 3]): File {
  return new File([new Uint8Array(bytes)], name, { type })
}

/** 伪造超大文件，避免真分配 10MB 内存 */
function withSize(file: File, size: number): File {
  Object.defineProperty(file, 'size', { value: size })
  return file
}

const mounted: VueWrapper[] = []

/** 挂载宿主组件以便在 setup 中调用 composable（含 onBeforeUnmount 注册） */
function mountHook() {
  const uploaded: File[] = []
  const removed: number[] = []
  let api!: ReturnType<typeof useFormImageUpload>
  const Host = defineComponent({
    setup() {
      api = useFormImageUpload(
        (file) => {
          uploaded.push(file)
        },
        () => {
          removed.push(1)
        },
      )
      return () => null
    },
  })
  const wrapper = mount(Host)
  mounted.push(wrapper)
  return { api, uploaded, removed, wrapper }
}

describe('打样项目图片上传：校验反馈与处理中状态', () => {
  const createObjectURL = vi.fn(() => 'blob:mock-url')
  const revokeObjectURL = vi.fn()

  beforeEach(() => {
    showToast.mockClear()
    createObjectURL.mockClear()
    revokeObjectURL.mockClear()
    // jsdom 未实现这两个 API，测试内以桩替代
    URL.createObjectURL = createObjectURL as unknown as typeof URL.createObjectURL
    URL.revokeObjectURL = revokeObjectURL as unknown as typeof URL.revokeObjectURL
  })

  afterEach(() => {
    while (mounted.length) mounted.pop()?.unmount()
    vi.restoreAllMocks()
  })

  it('非白名单类型：toast 报错、不上传、不产生预览', async () => {
    const { api, uploaded } = mountHook()
    await api.applyImageFile(makeFile('note.txt', 'text/plain'))

    expect(showToast).toHaveBeenCalledWith('仅支持 JPEG/PNG/WebP 格式', 'error')
    expect(uploaded).toHaveLength(0)
    expect(api.previewUrl.value).toBeNull()
  })

  it('超过 10MB：toast 报错、不上传、不产生预览', async () => {
    const { api, uploaded } = mountHook()
    await api.applyImageFile(withSize(makeFile('big.png', 'image/png'), 10 * 1024 * 1024 + 1))

    expect(showToast).toHaveBeenCalledWith('文件大小不能超过 10MB', 'error')
    expect(uploaded).toHaveLength(0)
    expect(api.previewUrl.value).toBeNull()
  })

  it('合规文件：回调收到 File 且产生预览', async () => {
    const { api, uploaded } = mountHook()
    await api.applyImageFile(makeFile('product.png', 'image/png'))

    expect(uploaded).toHaveLength(1)
    expect(uploaded[0]).toBeInstanceOf(File)
    expect(api.previewUrl.value).toBe('blob:mock-url')
    expect(showToast).not.toHaveBeenCalled()
  })

  it('处理期间 processing 为真，处理结束后回到假', async () => {
    const { api } = mountHook()
    const pending = api.applyImageFile(makeFile('product.png', 'image/png'))

    expect(api.processing.value).toBe(true)
    await pending
    expect(api.processing.value).toBe(false)
  })

  it('校验不通过时 processing 不会被点亮', async () => {
    const { api } = mountHook()
    await api.applyImageFile(makeFile('note.txt', 'text/plain'))

    expect(api.processing.value).toBe(false)
  })

  it('removeImage：回调 onRemove 且预览置空', async () => {
    const { api, removed } = mountHook()
    await api.applyImageFile(makeFile('product.png', 'image/png'))
    expect(api.previewUrl.value).toBe('blob:mock-url')

    api.removeImage()
    expect(removed).toHaveLength(1)
    expect(api.previewUrl.value).toBeNull()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock-url')
  })
})
