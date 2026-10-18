<template>
  <div class="ocr-page">
    <UiPageHeader>OCR 导入<template #description>上传发票或单据图片，自动识别并导入数据</template></UiPageHeader>

    <UiCard>
      <UiUpload accept=".pdf,.png,.jpg,.jpeg,.bmp,.tiff,.webp" multiple :disabled="uploading" @change="handleFileChange">
        <div class="upload-dragger-content" :class="{ 'is-disabled': uploading }">
          <FontAwesomeIcon icon="cloud-upload-alt" style="font-size: 48px; color: var(--color-text-muted)" aria-hidden="true" />
          <p style="margin-top: 12px">{{ uploading ? '识别中，请稍候…' : '拖拽文件到这里，或点击上传' }}</p>
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
      <div v-if="uploadResult" style="margin-top: 16px">
        <UiAlert v-if="uploadResult.errors?.length" variant="warning" :closable="false" style="margin-bottom: 12px">
          识别到 {{ uploadResult.errors.length }} 个错误：{{ uploadResult.errors.join('；') }}
        </UiAlert>
        <UiAlert v-if="uploadResult.total_imported" variant="success" :closable="false">
          成功识别 {{ uploadResult.total_imported }} 条记录
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
import { getErrorMessage, getErrorStatus } from '@/types/errors'

type UploadResult = {
  success?: boolean
  message?: string
  errors?: string[]
  total_imported?: number
}

/** /ocr-import/progress 轮询响应（后端键为 status/percent/message） */
interface OcrProgressResult {
  status: string
  percent?: number
  message?: string
}
// 2026-10-17 审计 AUD-03：后端写的是 done/percent，此前前端读 completed/percentage
// → 进度恒 0、终态永不命中、无限轮询。not_found 也必须是终态。
// 2026-10-18 OCR 评审：error 只是**单文件**失败状态，批量仍会继续并最终写 done，
// 不能当作批量终态。
const OCR_TERMINAL_STATUSES = ['done', 'completed', 'failed', 'not_found']

const taskId = ref('')
const progress = ref(0)
// 2026-10-18 OCR 评审：/progress 只有 status/message，不含 success/errors；
// 用上传响应判断「done 是否真的成功」，否则全失败也显示绿色「识别完成」。
const uploadResult = ref<UploadResult | null>(null)
/** 上传请求在途：轮询可能先看到 done（后端在返回响应前就写了终态），此时不能提前锁存结果 */
const uploading = ref(false)
/** 当前批次文件数：单文件时轮询的 percent 仍有意义（同一 task 不会被每文件重置） */
const batchSize = ref(0)

const progressStatus = ref<'' | 'success' | 'exception' | 'warning'>('')
const progressText = ref('处理中…')

/** 后端 MAX_OCR_FILE_SIZE 为 10MB；前端放宽会让文件到服务端才被跳过 */
const MAX_FILE_SIZE = 10 * 1024 * 1024
/** 后端 MAX_OCR_FILES = 50：超过会被整批 400 */
const MAX_FILES = 50

function beforeUpload(file: File) {
  if (file.size > MAX_FILE_SIZE) {
    showToast(`「${file.name}」超过 10MB 限制`, 'error')
    return false
  }
  return true
}

async function handleFileChange(files: FileList) {
  // 2026-10-18 OCR 评审：并发批次会把同一批文件重复写入暂存区（后端无幂等去重），
  // 批次进行中拒绝新的选择；只等 uploading（finally 必复位），不会像按进度状态判断那样卡死。
  if (uploading.value) {
    showToast('当前批次仍在识别中，请等待完成后再上传', 'info')
    return
  }
  // 2026-10-18 OCR 复评：不能把整批塞进一个请求——中间件对 /api/v1/* 的请求体
  // 上限是 10MB（含 multipart 开销），nginx client_max_body_size 也是 10m；
  // 几个中等图片就会 413。改为共用同一个 task_id、逐文件串行提交，结果在前端合并。
  const selected = Array.from(files).filter((f) => beforeUpload(f))
  if (selected.length > MAX_FILES) {
    showToast(`单次最多上传 ${MAX_FILES} 个文件`, 'error')
    return
  }
  if (!selected.length) return
  await handleUpload(selected)
}

// 轮询进度
// 轮询查询：数据在 queryFn 内直接落到本地 ref（progress/progressStatus/...），不解构 data
useQuery({
  queryKey: ['ocr-progress', taskId],
  queryFn: async () => {
    const tid = taskId.value
    if (!tid) return null
    const res = (await ocrApi.progress(tid)) as OcrProgressResult
    // 批次已切换：旧任务的迟到响应不得改动新批次的进度/终态
    if (tid !== taskId.value) return res
    // 已由本地收终态（全部未达后端）：迟到轮询不得把它改回成功/处理中
    if (progressStatus.value !== '') return res
    // 逐文件上传期间由本文件维护「上传中 i/N」文案与整体进度（按文件数），
    // 后端的 percent 每完成一个文件就写 100（同一 taskId），直接采用会显示错误进度。
    // 单文件批次没有「文件间」进度，轮询的 percent 是唯一有意义的进度来源。
    if (uploading.value) {
      if (batchSize.value === 1) progress.value = res.percent ?? 0
      return { status: 'processing' }
    }
    progress.value = res.percent ?? 0
    if (res.status === 'done' || res.status === 'completed') {
      const result = uploadResult.value
      if (result?.success === false) {
        progressStatus.value = 'exception'
        progressText.value = result.message || '识别失败'
      } else {
        progressStatus.value = 'success'
        progressText.value = '识别完成'
      }
    } else if (res.status === 'failed' || res.status === 'not_found') {
      progressStatus.value = 'exception'
      progressText.value = res.status === 'not_found' ? '任务不存在或已过期' : '识别失败'
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

async function handleUpload(files: File[]) {
  uploading.value = true
  batchSize.value = files.length
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
    uploadResult.value = null

    const merged: UploadResult = { total_imported: 0, errors: [] }
    let accepted = false
    let unknownCount = 0
    for (let i = 0; i < files.length; i++) {
      const file = files[i]!
      progress.value = Math.round((i / files.length) * 100)
      progressText.value = `上传中 ${i + 1}/${files.length}：${file.name}`
      const fd = new FormData()
      fd.append('files', file)
      try {
        // upload 必须携带 create-task 返回的 task_id，
        // 否则后端会新建另一个 task 写进度，前端轮询的 id 永远停在 pending。
        const res = await ocrApi.upload(sid, fd, sid) as UploadResult
        accepted = true
        merged.total_imported = (merged.total_imported ?? 0) + (res.total_imported ?? 0)
        if (res.errors?.length) merged.errors!.push(...res.errors)
      } catch (err: unknown) {
        // 单文件请求失败（413/超时/网络）不阻断其余文件，逐条上报。
        // 4xx 是服务端明确拒绝（413/403/422），肯定没写库；
        // 只有超时/断连/5xx 的服务端结果才是「未知」。
        const status = getErrorStatus(err)
        const unknown = status === undefined || status >= 500
        if (unknown) unknownCount += 1
        merged.errors!.push(
          `${file.name}: ${getErrorMessage(err, '上传失败')}`
          + (unknown ? '（结果未知，请先在暂存区核对再重试，避免重复导入）' : ''),
        )
      }
      progress.value = Math.round(((i + 1) / files.length) * 100)
    }
    merged.success = (merged.total_imported ?? 0) > 0
    merged.message = `共处理 ${files.length} 个文件，识别导入 ${merged.total_imported} 个出货到暂存区`
      + (unknownCount > 0 ? `（其中 ${unknownCount} 个结果未知，请核对）` : '')
    uploadResult.value = merged
    // 没有任何请求真正到达后端：服务端任务永远停在 pending，不能等轮询给终态。
    // 但「超时/5xx」是结果未知，不能断言文件未提交。
    if (!accepted) {
      progressStatus.value = 'exception'
      progress.value = 0
      progressText.value = unknownCount > 0
        ? '上传结果未知，请先在暂存区核对再重试'
        : (merged.errors?.length ? '文件未能提交，请查看下方错误' : '上传失败')
    }
  } catch (err: unknown) {
    const message = getErrorMessage(err, '上传失败')
    // 失败也写进 uploadResult：轮询看到 done 时据此显示失败而不是绿色完成
    uploadResult.value = { success: false, message }
    showToast(message, 'error')
    progressStatus.value = 'exception'
    progressText.value = message
  } finally {
    uploading.value = false
    batchSize.value = 0
  }
}
</script>

<style scoped>
.upload-dragger-content {
  text-align: center;
  padding: 40px 0;
}
.upload-dragger-content.is-disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.mt-16 {
  margin-top: 16px;
}
</style>
