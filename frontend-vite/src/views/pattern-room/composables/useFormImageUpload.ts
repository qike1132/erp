import { ref, onBeforeUnmount } from 'vue'

const UPLOAD_MAX_EDGE = 1600
const UPLOAD_QUALITY = 0.82

export function useFormImageUpload(
  onUpload: (file: File) => void,
  onRemove: () => void,
) {
  const previewUrl = ref<string | null>(null)

  function revokePreview() {
    if (previewUrl.value?.startsWith('blob:')) {
      URL.revokeObjectURL(previewUrl.value)
    }
  }

  function setPreview(url: string | null) {
    revokePreview()
    previewUrl.value = url
  }

  async function compressImageFile(file: File): Promise<File> {
    if (file.type === 'image/webp' && file.size <= 1.5 * 1024 * 1024) return file
    try {
      const bitmap = await createImageBitmap(file)
      const { width, height } = bitmap
      const scale = Math.min(1, UPLOAD_MAX_EDGE / Math.max(width, height))
      if (scale === 1 && file.type === 'image/jpeg' && file.size <= 2 * 1024 * 1024) {
        bitmap.close()
        return file
      }
      const canvas = document.createElement('canvas')
      canvas.width = Math.max(1, Math.round(width * scale))
      canvas.height = Math.max(1, Math.round(height * scale))
      const ctx = canvas.getContext('2d')
      if (!ctx) {
        bitmap.close()
        return file
      }
      ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
      bitmap.close()
      const stem = file.name.replace(/\.(jpe?g|png|webp)$/i, '') || 'image'
      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/webp', UPLOAD_QUALITY))
      if (blob && blob.type === 'image/webp') {
        return new File([blob], `${stem}.webp`, { type: 'image/webp' })
      }
      const jpegBlob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', UPLOAD_QUALITY))
      if (jpegBlob) {
        return new File([jpegBlob], `${stem}.jpg`, { type: 'image/jpeg' })
      }
      return file
    } catch (e) {
      console.warn('[ProjectFormDialog] 图片压缩失败，使用原图:', e)
      return file
    }
  }

  async function applyImageFile(file: File) {
    const allowed = ['image/jpeg', 'image/png', 'image/webp']
    if (!allowed.includes(file.type)) return
    if (file.size > 10 * 1024 * 1024) return
    const finalFile = await compressImageFile(file)
    revokePreview()
    previewUrl.value = URL.createObjectURL(finalFile)
    onUpload(finalFile)
  }

  function removeImage() {
    revokePreview()
    previewUrl.value = null
    onRemove()
  }

  onBeforeUnmount(revokePreview)

  return { previewUrl, setPreview, applyImageFile, removeImage, revokePreview }
}