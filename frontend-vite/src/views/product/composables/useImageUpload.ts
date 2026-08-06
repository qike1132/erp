import { upload } from '@/api/request'
import { showToast } from '@/composables/useToast'

const ALLOWED_TYPES = ['image/jpeg', 'image/png', 'image/gif']
const MAX_SIZE = 5 * 1024 * 1024

/**
 * 上传图片到 /auth/upload 端点。
 * 校验文件类型与大小，成功后回调返回 URL。
 */
export function uploadImage(file: File, onSuccess: (url: string) => void): void {
  if (!ALLOWED_TYPES.includes(file.type)) {
    showToast('仅支持 JPG/PNG/GIF 格式', 'error')
    return
  }
  if (file.size > MAX_SIZE) {
    showToast('文件大小不能超过 5MB', 'error')
    return
  }
  const formData = new FormData()
  formData.append('file', file)
  upload<{ url: string }>('/auth/upload', formData)
    .then((data) => {
      if (data.url) onSuccess(data.url)
    })
    .catch(() => showToast('上传失败', 'error'))
}
