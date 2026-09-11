import { upload } from '@/api/request'
import { showToast } from '@/composables/useToast'

/** 允许的图片类型（拖拽 / 选择文件 / 粘贴 三个入口共用同一份白名单） */
export const ALLOWED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/gif']
/** 界面展示用的格式提示文案 */
export const ALLOWED_IMAGE_HINT = 'JPG / PNG / GIF'
export const MAX_IMAGE_SIZE = 5 * 1024 * 1024

const MIME_EXT: Record<string, string> = {
  'image/jpeg': 'jpg',
  'image/png': 'png',
  'image/gif': 'gif',
}
const EXT_MIME: Record<string, string> = {
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  png: 'image/png',
  gif: 'image/gif',
}

/** 解析真实 MIME：优先 file.type；剪贴板来源可能缺失，则按扩展名兜底 */
function resolveMime(file: File): string {
  const type = (file.type || '').toLowerCase()
  if (type) return type
  const ext = /\.([a-z0-9]+)$/i.exec(file.name || '')?.[1]?.toLowerCase() ?? ''
  return EXT_MIME[ext] ?? ''
}

/**
 * 规整文件名。
 * 剪贴板/截图来源的 File 常常没有文件名或没有扩展名，而后端 /auth/upload
 * 依赖扩展名做白名单校验，因此这里按 MIME 补齐后再提交。
 */
function normalizeImageFile(file: File, mime: string): File {
  const rawName = (file.name || '').trim()
  const base = rawName.replace(/\.[^.]*$/, '')
  const name = /\.(jpe?g|png|gif)$/i.test(rawName) ? rawName : `${base || `pasted-${Date.now()}`}.${MIME_EXT[mime]}`
  if (name === file.name && file.type === mime) return file
  return new File([file], name, { type: mime, lastModified: file.lastModified || Date.now() })
}

/**
 * 统一校验：类型 + 大小。
 * 通过则返回规整后的 File，不通过返回 null（已弹出提示）。
 */
export function validateImageFile(file: File): File | null {
  const mime = resolveMime(file)
  if (!ALLOWED_IMAGE_TYPES.includes(mime)) {
    showToast('仅支持 JPG/PNG/GIF 格式', 'error')
    return null
  }
  if (file.size > MAX_IMAGE_SIZE) {
    showToast(`文件大小不能超过 ${MAX_IMAGE_SIZE / 1024 / 1024}MB`, 'error')
    return null
  }
  return normalizeImageFile(file, mime)
}

/**
 * 上传图片到 /auth/upload 端点。
 * 校验文件类型与大小，成功后回调返回 URL。
 */
export function uploadImage(file: File, onSuccess: (url: string) => void): void {
  const valid = validateImageFile(file)
  if (!valid) return
  const formData = new FormData()
  formData.append('file', valid)
  upload<{ url: string }>('/auth/upload', formData)
    .then((data) => {
      if (data.url) onSuccess(data.url)
    })
    .catch(() => showToast('上传失败', 'error'))
}
