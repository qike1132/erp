<template>
  <div class="ocr-page">
    <UiPageHeader>OCR 导入<template #description>上传发票或单据图片，自动识别并导入数据</template></UiPageHeader>

    <UiCard>
      <UiUpload accept=".pdf,.png,.jpg,.jpeg,.bmp,.tiff,.webp" multiple @change="handleFileChange">
        <div class="upload-dragger-content">
          <i class="fas fa-cloud-upload-alt" style="font-size: 48px; color: var(--color-text-muted)" />
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
import { upload as apiUpload } from '@/api/request'
import UiCard from '@/components/ui/UiCard.vue'
import UiUpload from '@/components/ui/UiUpload.vue'
import UiProgress from '@/components/ui/UiProgress.vue'
import UiAlert from '@/components/ui/UiAlert.vue'
import UiPageHeader from '@/components/ui/UiPageHeader.vue'

import { showToast } from '@/composables/useToast'

type UploadOptions = { file: File; onProgress?: (e: { percent: number }) => void }

const taskId = ref('')
const progress = ref(0)
const ocrResult = ref<any>(null)

const progressStatus = ref<'' | 'success' | 'exception' | 'warning'>('')
const progressText = ref('处理中...')

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
    if (!beforeUpload(file)) continue
    handleUpload({ file })
  }
}

// 轮询进度
const { data: progressData } = useQuery({
  queryKey: ['ocr-progress', taskId],
  queryFn: async () => {
    if (!taskId.value) return null
    const res = (await ocrApi.progress(taskId.value)) as any
    progress.value = res.percentage ?? 0
    if (res.status === 'completed') {
      progressStatus.value = 'success'
      progressText.value = '识别完成'
      ocrResult.value = res
    } else if (res.status === 'failed') {
      progressStatus.value = 'exception'
      progressText.value = '识别失败'
      ocrResult.value = res
    } else {
      progressText.value = `处理中 ${progress.value}%`
    }
    return res
  },
  enabled: () => !!taskId.value && progressStatus.value === '',
  refetchInterval: (query) => {
    const data = query.state.data as any
    if (data?.status === 'completed' || data?.status === 'failed') return false
    return 800
  },
})

async function handleUpload(options: UploadOptions) {
  try {
    const createRes = (await ocrApi.createTask()) as any
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
    await apiUpload(`/ocr-import/upload?session_id=${sid}`, formData)

    showToast('文件上传成功，开始识别...', 'success')
  } catch (err: any) {
    showToast(err.response?.data?.detail || '上传失败', 'error')
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
