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

/** GET /orders/records 查询参数（B1 契约，与后端 list_unified_records 对齐） */
export interface OrderRecordsQuery {
  /** 页码（后端 ge=1） */
  page?: number
  /** 每页数量（后端 ge=1, le=500） */
  per_page?: number
  /** 记录类型：all=全部 / order=订单 / stockin=备货（后端默认 all） */
  record_type?: 'all' | 'order' | 'stockin'
  /** 产品名称或条码模糊 */
  product?: string
  /** 单号或编号模糊 */
  order_no?: string
  customer?: string
  status?: string
  factory?: string
  start_date?: string
  end_date?: string
  [key: string]: unknown
}

/**
 * 统一记录行（订单+备货合并，GET /orders/records，B1 契约）。
 * 备货行的 order_no 来自 stockin_no、order_date 来自 stockin_date、status 为 null。
 */
export interface UnifiedRecord {
  id: number
  record_type: 'order' | 'stockin'
  order_no: string
  customer: string
  order_date: string
  /** 备货行为 null */
  status: string | null
  product: { id: number; name: string; barcode: string; image: string } | null
  quantity: number
  /** 备货行为 0（后端已聚合，前端无需再按 i.deducted 补算） */
  deduct_quantity: number
  factories: string[]
  items?: Array<{
    id: number
    product_id?: number | null
    product_name?: string | null
    product_barcode?: string | null
    product_image?: string
    quantity: number
    deduct_quantity?: number
    note?: string
  }>
}

/** GET /orders/records 响应（B1 契约） */
export interface OrderRecordsResponse {
  success: boolean
  data: UnifiedRecord[]
  total: number
  page: number
  per_page: number
}

export const orderApi = {
  list: (params?: QueryParams) => get<OrderListApiResponse>('/orders/list', params),
  records: (params?: OrderRecordsQuery) => get<OrderRecordsResponse>('/orders/records', params),
  beileList: (params?: QueryParams) => get<OrderListApiResponse>('/orders/beile-list', params),
  detail: (id: number) => get<OrderItem>(`/orders/${id}`),
  create: (data: Partial<OrderItem>) => post<OrderItem>('/orders/create', data),
  update: (id: number, data: Partial<OrderItem>) => put<OrderItem>(`/orders/edit/${id}`, data),
  delete: (id: number) => del(`/orders/delete/${id}`),
  /** 编辑单个订单明细（SKU）：数量/备注（报表流水行内编辑，2026-10-13） */
  updateItem: (id: number, data: { quantity?: number; note?: string }) =>
    put<OrderItem>(`/orders/items/${id}`, data),
  /** 删除单个订单明细（SKU）；删到空等价删整单（走整单删除的审批/备份） */
  deleteItem: (id: number) => del(`/orders/items/${id}`),
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
