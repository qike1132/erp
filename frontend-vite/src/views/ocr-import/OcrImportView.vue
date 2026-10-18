<template>
  <div class="ocr-page">
    <UiPageHeader>OCR 导入<template #description>上传发票或单据图片，自动识别并导入数据</template></UiPageHeader>

    <UiCard>
      <UiUpload accept=".pdf,.png,.jpg,.jpeg,.bmp,.tiff,.webp" multiple @change="handleFileChange">
        <div class="upload-dragger-content">
          <FontAwesomeIcon icon="cloud-upload-alt" style="font-size: 48px; color: var(--color-text-muted)" aria-hidden="true" />
          <p style="margin-top: 12px">拖拽文件到这里，或点击上传</p>
          <p style="color: var(--color-text-muted); font-size: 12px">支持 PDF/PNG/JPG/BMP/TIFF/WEBP</p>
        </div>
      </UiUpload>
    </UiCard>

    <!-- 进度 -->
    <UiCard v-if="taskId" padding-class="mt-16" body-padding>
      <div style="display: flex; align-items: center; gap: 16px">
        <UiProgress
          :percentage="progress"
          :status="progressStatus === 'success' ? 'success' : progressStatus === 'exception' ? 'danger' : undefined"
          style="flex: 1"
          show-text
        />
        <span>{{ progressText }}</span>
      </div>
      <div v-if="ocrResult" style="margin-top: 16px">
        <UiAlert v-if="ocrResult.errors?.length" variant="warning" :closable="false" style="margin-bottom: 12px">
          识别到 {{ ocrResult.errors.length }} 个错误
        </UiAlert>
        <UiAlert v-if="ocrResult.success_count" variant="success" :closable="false">
          成功识别 {{ ocrResult.success_count }} 条记录
        </UiAlert>
      </div>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { ocrApi } from '@/api'
import UiCard from '@/components/ui/UiCard.vue'
import UiUpload from '@/components/ui/UiUpload.vue'
import UiProgress from '@/components/ui/UiProgress.vue'
import UiAlert from '@/components/ui/UiAlert.vue'
import UiPageHeader from '@/components/ui/UiPageHeader.vue'

import { showToast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'

type UploadOptions = { file: File; onProgress?: (e: { percent: number }) => void }

/** /ocr-import/progress 轮询响应（后端键为 status/percent/message） */
interface OcrProgressResult {
  progress?: number
  status: string
  percent?: number
  message?: string
  percentage?: number
  success_count?: number
  errors?: string[]
}

// 2026-10-17 审计 AUD-03：后端写的是 done/percent，此前前端读 completed/percentage
// → 进度恒 0、终态永不命中、无限轮询。not_found 也必须是终态。
// 2026-10-18 OCR 评审：error 只是**单文件**失败状态，批量仍会继续并最终写 done，
// 不能当作批量终态。
const OCR_TERMINAL_STATUSES = ['done', 'completed', 'failed', 'not_found']

const taskId = ref('')
const progress = ref(0)
const ocrResult = ref<OcrProgressResult | null>(null)

const progressStatus = ref<'' | 'success' | 'exception' | 'warning'>('')
const progressText = ref('处理中…')

function beforeUpload(file: File) {
  const maxSize = 20 * 1024 * 1024
  if (file.size > maxSize) {
    showToast('文件大小不能超过 20MB', 'error')
    return false
  }
  return true
}

function handleFileChange(files: FileList) {
  for (let i = 0; i < files.length; i++) {
    const file = files[i]
    if (!file || !beforeUpload(file)) continue
    handleUpload({ file })
  }
}

// 轮询进度
// 轮询查询：数据在 queryFn 内直接落到本地 ref（progress/progressStatus/...），不解构 data
useQuery({
  queryKey: ['ocr-progress', taskId],
  queryFn: async () => {
    if (!taskId.value) return null
    const res = (await ocrApi.progress(taskId.value)) as OcrProgressResult
    progress.value = res.percent ?? res.percentage ?? 0
    if (res.status === 'done' || res.status === 'completed') {
      progressStatus.value = 'success'
      progressText.value = '识别完成'
      ocrResult.value = res
    } else if (res.status === 'failed' || res.status === 'not_found') {
      progressStatus.value = 'exception'
      progressText.value = res.status === 'not_found' ? '任务不存在或已过期' : '识别失败'
      ocrResult.value = res
    } else {
      progressText.value = `处理中 ${progress.value}%`
    }
    return res
  },
  enabled: () => !!taskId.value && progressStatus.value === '',
  refetchInterval: (query) => {
    const data = query.state.data as { status: string } | null
    if (data && OCR_TERMINAL_STATUSES.includes(data.status)) return false
    return 800
  },
})

async function handleUpload(options: UploadOptions) {
  try {
    const createRes = (await ocrApi.createTask()) as unknown as { task_id?: string; session_id?: string }
    const sid = createRes.task_id ?? createRes.session_id
    if (!sid) {
      showToast('创建任务失败', 'error')
      return
    }

    taskId.value = sid
    progress.value = 0
    progressStatus.value = ''
    progressText.value = '上传中...'
    ocrResult.value = null

    const formData = new FormData()
    formData.append('file', options.file)
    // 2026-10-18 OCR 评审 H-2：upload 必须携带 create-task 返回的 task_id，
    // 否则后端会新建另一个 task 写进度，前端轮询的 id 永远停在 pending。
    await ocrApi.upload(sid, formData, sid)

    showToast('文件上传成功，开始识别...', 'success')
  } catch (err: unknown) {
    showToast(getErrorMessage(err, '上传失败'), 'error')
    progressStatus.value = 'exception'
  }
}
</script>

<style scoped>
.upload-dragger-content {
  text-align: center;
  padding: 40px 0;
}
.mt-16 {
  margin-top: 16px;
}
</style>
