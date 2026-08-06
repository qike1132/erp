import { ref, reactive, onUnmounted } from 'vue'
import { post } from '@/api/request'
import { ocrApi } from '@/api'
import { showToast } from '@/composables/useToast'
import type { ApiResponse } from '@/types'

// OCR 文件上传校验常量
const ALLOWED_MIME_TYPES = ['application/pdf']
const ALLOWED_EXTENSIONS = ['.pdf']
const MAX_FILE_SIZE = 20 * 1024 * 1024 // 20MB
const MAX_FILE_COUNT = 10

/** 校验 OCR 上传文件：类型白名单 + 大小限制 + 数量限制 */
function validateOcrFiles(files: File[]): File[] {
  const valid: File[] = []
  for (const file of files) {
    const ext = file.name.toLowerCase().match(/\.[^.]+$/)?.[0] || ''
    if (!ALLOWED_MIME_TYPES.includes(file.type) && !ALLOWED_EXTENSIONS.includes(ext)) {
      showToast(`仅支持 PDF 格式，已跳过: ${file.name}`, 'error')
      continue
    }
    if (file.size > MAX_FILE_SIZE) {
      showToast(`文件超过 20MB 限制: ${file.name}`, 'error')
      continue
    }
    valid.push(file)
  }
  if (valid.length > MAX_FILE_COUNT) {
    showToast(`最多上传 ${MAX_FILE_COUNT} 个文件`, 'error')
    return valid.slice(0, MAX_FILE_COUNT)
  }
  return valid
}

export function useOcrImport(onComplete: () => void) {
  const pdfFiles = ref<File[]>([])
  const ocrPreviewing = ref(false)
  const ocrImporting = ref(false)
  const ocrProgress = reactive({ show: false, pct: 0, msg: '准备中...' })
  const ocrInputRef = ref<HTMLInputElement | null>(null)
  const ocrDragOver = ref(false)
  const isUnmounted = ref(false)
  let ocrProgressTimeout: ReturnType<typeof setTimeout> | null = null

  onUnmounted(() => {
    isUnmounted.value = true
    if (ocrProgressTimeout) clearTimeout(ocrProgressTimeout)
  })

  function onOcrFileSelect(event: Event) {
    const input = event.target as HTMLInputElement
    const files = input.files ? Array.from(input.files) : []
    pdfFiles.value = validateOcrFiles(files)
  }

  function onOcrDrop(event: DragEvent) {
    ocrDragOver.value = false
    const files = event.dataTransfer?.files
    if (!files) return
    pdfFiles.value = validateOcrFiles(Array.from(files))
  }

  async function handleOcrPreview() {
    if (!pdfFiles.value.length) return
    ocrPreviewing.value = true
    try {
      const fd = new FormData()
      pdfFiles.value.forEach(f => fd.append('files', f))
      const res = await post('/ocr-import/preview', fd) as ApiResponse
      showToast(res.message || '预览完成', 'info')
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } } }
      showToast(error.response?.data?.detail || '预览失败', 'error')
    } finally {
      ocrPreviewing.value = false
    }
  }

  async function handleOcrImport() {
    if (!pdfFiles.value.length) return
    ocrImporting.value = true
    ocrProgress.show = true
    ocrProgress.pct = 0
    ocrProgress.msg = '创建任务...'
    try {
      const task = await ocrApi.createTask() as ApiResponse & { task_id?: string; id?: string }
      const taskId = task.task_id || task.id
      if (!taskId) throw new Error('创建OCR任务失败')

      ocrProgress.msg = '上传文件...'
      ocrProgress.pct = 20
      const fd = new FormData()
      pdfFiles.value.forEach(f => fd.append('files', f))
      await ocrApi.upload(taskId, fd)

      ocrProgress.msg = 'OCR识别中...'
      let completed = false
      let attempts = 0
      const MAX_OCR_ATTEMPTS = 60
      while (!completed && attempts < MAX_OCR_ATTEMPTS && !isUnmounted.value) {
        await new Promise(r => setTimeout(r, 2000))
        attempts++
        const prog = await ocrApi.progress(taskId)
        const pct = prog.progress ?? 0
        ocrProgress.pct = Math.min(90, 20 + pct * 0.7)
        ocrProgress.msg = prog.status || '处理中…'
        if (prog.status === 'completed' || prog.status === 'done' || prog.progress >= 100) {
          completed = true
        }
      }
      if (attempts >= MAX_OCR_ATTEMPTS || isUnmounted.value) {
        ocrProgress.msg = 'OCR处理超时，请稍后刷新查看'
        return
      }

      ocrProgress.pct = 100
      ocrProgress.msg = '导入完成'
      showToast('OCR识别导入完成', 'success')
      pdfFiles.value = []
      onComplete()
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } } }
      showToast(error.response?.data?.detail || 'OCR导入失败', 'error')
    } finally {
      ocrImporting.value = false
      if (ocrProgressTimeout) clearTimeout(ocrProgressTimeout)
      ocrProgressTimeout = setTimeout(() => { ocrProgress.show = false }, 2000)
    }
  }

  return {
    pdfFiles, ocrPreviewing, ocrImporting, ocrProgress, ocrInputRef, ocrDragOver,
    onOcrFileSelect, onOcrDrop, handleOcrPreview, handleOcrImport,
  }
}
