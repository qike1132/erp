import { get } from './request'
import type { BatchQueryItem, QueryParams } from '@/types'

/** 批次查询列表响应（与后端 BatchQueryListResponse 对齐） */
interface BatchQueryListResponse {
  success: boolean
  data: BatchQueryItem[]
  total: number
  page: number
  per_page: number
}

export const batchApi = {
  list: (params?: Record<string, unknown>) =>
    get<BatchQueryListResponse>('/order-batch/batch-query', params),
}
