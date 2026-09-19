import { get, post, put, del, upload } from './request'
import type {
  OrderItem, StagingImportResult, StagingListResponse, StagingRow, QueryParams,
} from '@/types'

/** 暂存区 Excel 导入：解析 + 写库耗时远超全局 15s（与 stock / plan 的导入约定一致） */
const STAGING_IMPORT_TIMEOUT = 120_000

/** 订单列表响应（对应后端 OrderListResponse schema） */
export interface OrderListApiResponse {
  success: boolean
  data: OrderItem[]
  total: number
  page: number
  per_page: number
  /** 未确认湖北订单总数（beile-list 专用，顶部横幅） */
  unconfirmed_count?: number
}

export interface ConfirmOrderResponse {
  success: boolean
  message: string
}

export const orderApi = {
  list: (params?: QueryParams) => get<OrderListApiResponse>('/orders/list', params),
  beileList: (params?: QueryParams) => get<OrderListApiResponse>('/orders/beile-list', params),
  detail: (id: number) => get<OrderItem>(`/orders/${id}`),
  create: (data: Partial<OrderItem>) => post<OrderItem>('/orders/create', data),
  update: (id: number, data: Partial<OrderItem>) => put<OrderItem>(`/orders/edit/${id}`, data),
  delete: (id: number) => del(`/orders/delete/${id}`),
  lock: (id: number) => post(`/orders/lock/${id}`),
  unlock: (id: number) => post(`/orders/unlock/${id}`),
  deductStock: (id: number) => post(`/orders/deduct-stock/${id}`),
  updateDeduct: (id: number, deductQuantity: number) => put(`/orders/deduct/${id}?deduct_quantity=${deductQuantity}`),
  confirmBeileOrder: (id: number) => post<ConfirmOrderResponse>(`/orders/${id}/confirm`),
  confirmBeileStockin: (id: number) => post<ConfirmOrderResponse>(`/orders/stockin/${id}/confirm`),
  /**
   * 暂存订单（后端 `api/v1/endpoints/staging_order.py`，前缀 `/staging-orders`）。
   *
   * 可用端点只有：`GET ''`、`POST /import`、`POST /confirm`、`PUT /{id}`、
   * `DELETE /clear`、`DELETE /clear-session/{session_id}`、`DELETE /{id}`。
   *
   * ⚠️ 修正记录（2026-09-18）：原声明的 `POST /staging-orders/add` 与
   * `GET /staging-orders/list` **后端都不存在**，且 list 的返回类型被写成裸数组
   * （真实响应是 `{success, data, total}`）。手工录入不经此域——它由录入页本地
   * 暂存 + `POST /aux/batch-submit-orders` 承担；批量导入请走 `/staging-orders/import`。
   */
  staging: {
    /** 列表查询；`params` 用于分页取全（后端单页上限 500，默认仅 100 条） */
    list: <T = StagingRow>(sessionId?: string, params?: { page?: number; per_page?: number }) =>
      get<StagingListResponse<T>>('/staging-orders', {
        ...(sessionId ? { session_id: sessionId } : {}),
        ...params,
      }),
    /** 导入 Excel 到暂存区（**先清空**当前会话暂存区再写入本次全部行） */
    importExcel: (formData: FormData) =>
      upload<StagingImportResult>('/staging-orders/import', formData, undefined, STAGING_IMPORT_TIMEOUT),
    delete: (id: number) => del(`/staging-orders/${id}`),
    confirm: () => post('/staging-orders/confirm'),
  },
}
