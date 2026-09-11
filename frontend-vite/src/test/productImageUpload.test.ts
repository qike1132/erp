import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// hoisted：保证 mock 变量先于 vi.mock 工厂初始化
const { showToast, upload } = vi.hoisted(() => ({
  showToast: vi.fn((_message: string, _type?: string) => undefined),
  upload: vi.fn((_url: string, _formData: FormData) => Promise.resolve({ url: '/static/uploads/a.png' })),
}))

vi.mock('@/composables/useToast', () => ({ showToast }))
vi.mock('@/api/request', () => ({ upload }))

import { validateImageFile, uploadImage, ALLOWED_IMAGE_TYPES } from '../views/product/composables/useImageUpload'

/** 构造一个 File；content 用最小合法字节即可，size 不参与构造 */
function makeFile(name: string, type: string, bytes = [1, 2, 3]): File {
  return new File([new Uint8Array(bytes)], name, { type })
}

/** 伪造超大文件，避免真分配 5MB 内存 */
function withSize(file: File, size: number): File {
  Object.defineProperty(file, 'size', { value: size })
  return file
}

describe('产品图片上传校验（拖拽 / 选择 / 粘贴 共用）', () => {
  beforeEach(() => {
    showToast.mockClear()
    upload.mockClear()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('白名单为 JPG / PNG / GIF', () => {
    expect(ALLOWED_IMAGE_TYPES).toEqual(['image/jpeg', 'image/png', 'image/gif'])
  })

  it('合规文件通过校验并保留原文件名', () => {
    const file = makeFile('photo.png', 'image/png')
    const valid = validateImageFile(file)
    expect(valid).not.toBeNull()
    expect(valid!.name).toBe('photo.png')
    expect(valid!.type).toBe('image/png')
    expect(showToast).not.toHaveBeenCalled()
  })

  it('剪贴板无文件名时按 MIME 补齐扩展名（后端依赖扩展名做白名单）', () => {
    const valid = validateImageFile(makeFile('', 'image/png'))
    expect(valid?.name).toMatch(/^pasted-\d+\.png$/)
    expect(valid?.type).toBe('image/png')
  })

  it('剪贴板无 MIME 时按扩展名兜底推断', () => {
    const valid = validateImageFile(makeFile('snip.JPG', ''))
    expect(valid).not.toBeNull()
    expect(valid!.type).toBe('image/jpeg')
  })

  it('无 MIME 且无扩展名 → 拒绝', () => {
    expect(validateImageFile(makeFile('', ''))).toBeNull()
    expect(showToast).toHaveBeenCalledWith('仅支持 JPG/PNG/GIF 格式', 'error')
  })

  it('webp 等未在白名单内的图片 → 拒绝（与拖拽限制一致）', () => {
    expect(validateImageFile(makeFile('a.webp', 'image/webp'))).toBeNull()
    expect(showToast).toHaveBeenCalledWith('仅支持 JPG/PNG/GIF 格式', 'error')
  })

  it('超过 5MB → 拒绝', () => {
    const big = withSize(makeFile('big.png', 'image/png'), 5 * 1024 * 1024 + 1)
    expect(validateImageFile(big)).toBeNull()
    expect(showToast).toHaveBeenCalledWith('文件大小不能超过 5MB', 'error')
  })

  it('校验不过时不发起上传请求', () => {
    uploadImage(makeFile('a.webp', 'image/webp'), vi.fn())
    expect(upload).not.toHaveBeenCalled()
  })

  it('校验通过时以规整后的文件名提交，并回调 URL', async () => {
    const onSuccess = vi.fn<(url: string) => void>()
    uploadImage(makeFile('', 'image/jpeg'), onSuccess)
    expect(upload).toHaveBeenCalledTimes(1)
    const call = upload.mock.calls[0]
    expect(call).toBeDefined()
    const formData = call![1]
    const submitted = formData.get('file') as File
    expect(submitted.name).toMatch(/^pasted-\d+\.jpg$/)
    await vi.waitFor(() => expect(onSuccess).toHaveBeenCalledWith('/static/uploads/a.png'))
  })
})
