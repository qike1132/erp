import { get, upload, download } from './request'
import type { BatchImportResult, BatchQueryItem, QueryParams } from '@/types'

/** Excel 解析 + 落库耗时远超全局 15s 超时（与 stock / plan 的导入约定一致） */
const IMPORT_TIMEOUT = 120_000

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

  /**
   * 批量导入产品（`POST /batch/batch-import`）。
   *
   * ⚠️ 修正记录（2026-09-18）：原调用点写的是 `/batch/import-products`，**该路由不存在**
   * （`batch.py` 实际注册的是 `batch-import`），前端导入产品会稳定 404。
   * `batch.py` 现存路由仅：download-template / import-orders / import-case-stockouts /
   * import-case-stockins / import-stockins / import-stockouts / batch-import / import-comprehensive。
   */
  importProducts: (formData: FormData) =>
    upload<BatchImportResult>('/batch/batch-import', formData, undefined, IMPORT_TIMEOUT),

  /** 下载统一导入模板（`GET /batch/download-template`） */
  downloadTemplate: (filename = '统一导入模板.xlsx') => download('/batch/download-template', filename),
}
