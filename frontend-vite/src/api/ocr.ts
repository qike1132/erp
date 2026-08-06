import { get, post, upload } from './request'
import type { TaskResponse } from '@/types'

export const ocrApi = {
  createTask: () => post<TaskResponse>('/ocr-import/create-task'),
  upload: (sessionId: string, formData: FormData) => upload('/ocr-import/upload', formData),
  progress: (taskId: string) => get<{ progress: number; status: string }>(`/ocr-import/progress/${taskId}`),
}
