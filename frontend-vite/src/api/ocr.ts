import { get, post, upload } from './request'
import type { TaskResponse } from '@/types'

/** OCR 预览耗时与文件数/页数成正比，放宽全局 15s 超时 */
const PREVIEW_TIMEOUT = 120_000

export const ocrApi = {
  createTask: () => post<TaskResponse>('/ocr-import/create-task'),
  /** 预览 OCR 识别结果（不写入暂存区）；后端 `response_model=OcrPdfPreviewResult` */
  preview: (formData: FormData) => upload<Record<string, unknown>>('/ocr-import/preview', formData, undefined, PREVIEW_TIMEOUT),
  /**
   * 上传 PDF/图片走离线 OCR 并写入暂存出货区（`POST /ocr-import/upload`）。
   *
   * ⚠️ 修正记录（2026-09-18）：`session_id` 后端为 **Query(..., 必填)**，原实现收了
   * `sessionId` 参数却**没有拼进 URL**（静默丢弃）→ 后端必然 422。
   * 两处调用方各自绕开本函数手拼 URL 才得以工作（`OcrImportView.vue` 与 `useOcrImport.ts`），
   * 这正是「API 层与实际契约脱节」的典型表现。现补回参数并由调用方统一走本函数。
   */
  upload: (sessionId: string, formData: FormData) =>
    upload(`/ocr-import/upload?session_id=${encodeURIComponent(sessionId)}`, formData),
  progress: (taskId: string) => get<{ progress: number; status: string }>(`/ocr-import/progress/${taskId}`),
}
