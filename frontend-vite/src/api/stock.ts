import { get, post, put, del, upload, download } from './request'
import type {
  Product, StagingListResponse, StagingRow, StagingImportResult,
  InventoryResponse, StockInRecord, ShipmentInfo, ApiResponse, QueryParams,
} from '@/types'
import type { StockStatsData, StockStatsResponse } from '@/types/api'

/**
 * `/aux/batch-submit-orders` / `-stockins` / `-stockouts` 的批量提交响应。
 *
 * 后端逐个返回 results；调用方按 `results[].success` 判定部分失败（HTTP 恒为 200）。
 * 保留 `data` 键以兼容历史 `{ data }` 包裹响应。
 */
export interface BatchSubmitResponse {
  success?: boolean
  created_count?: number
  results?: { success: boolean; error?: string }[]
  data?: BatchSubmitResponse
}

/** 暂存区导入链路超时：Excel 解析 + 写暂存区可能远超全局 15s（同 planApi 的导入约定） */
const STAGING_IMPORT_TIMEOUT = 120_000

/**
 * 编辑备货的请求体（对应后端 `schemas/stock.py::StockInUpdate`）。
 *
 * 部分更新语义：未提供的字段沿用记录原值。**没有 product_id** ——
 * 换产品等于换一条备货记录，后端也不接受。
 */
export interface StockInUpdatePayload {
  quantity?: number
  customer?: string
  /** `YYYY-MM-DD`；只传日期时后端保留原记录的时间部分 */
  stockin_date?: string
  note?: string
}

/** 编辑出货的请求体（后端 `schemas/stock.py::StockOutUpdate`，独立出货与备货抵扣共用） */
export interface StockOutUpdatePayload {
  quantity?: number
  customer?: string
  stockout_date?: string
  note?: string
}

/** 报表「出货/抵扣流水」聚合行还原出的明细行（GET /stock/out/records） */
export interface StockFlowRecord {
  id: number
  stockout_no: string
  stockout_date: string
  customer: string
  product_id: number
  product_name: string
  barcode: string
  quantity: number
  returned_quantity: number
  note: string
  stockin_id: number | null
  order_id: number | null
}

export const stockApi = {
  stats: async (): Promise<StockStatsData> => {
    // 同 dashboardApi.stats：该请求归 Vue Query 缓存所有，不能参与路由级取消
    // （取消会让查询永久卡在 fetching，首次登录仪表盘因此无数据）。
    const resp = await get<StockStatsResponse>('/stock/stats', undefined, { routeCancel: false })
    // 信封异常必须显式失败：此前 `resp.data ?? (resp as StockStatsData)` 会把整个
    // 信封对象当数据返回，order_quantity/stockin_quantity 全为 undefined，
    // 仪表盘静默渲染坏值（与 useDashboardStats.fetchStats 的口径对齐）。
    if (!resp?.data) throw new Error('API 返回数据格式异常：data 字段缺失')
    return resp.data
  },
  stockins: (params?: QueryParams) => get<StockInRecord[]>('/stock/in/list', params),
  inventory: (params?: QueryParams) => get<InventoryResponse>('/stock/inventory', params),
  editStockin: (id: number, data: StockInUpdatePayload) =>
    put<{ success?: boolean; message?: string }>(`/stock/in/edit/${id}`, data),
  deleteStockin: (id: number) => del(`/stock/in/delete/${id}`),
  /**
   * 报表「出货/抵扣流水」聚合行还原（按单号取明细，供行内编辑/删除）。
   * kind='stockout' 按 stockout_no 匹配独立出货；kind='deduction' 按订单号匹配备货抵扣。
   * product 传行内产品名收窄：同一订单可能对多个产品分别抵扣，只凭订单号会串到他产品。
   */
  stockoutRecords: (kind: 'stockout' | 'deduction', nos: string, product = '') =>
    get<{ success?: boolean; data: StockFlowRecord[] }>('/stock/out/records', {
      kind, nos, ...(product ? { product } : {}),
    }),
  /** 编辑出货/抵扣行（抵扣行后端会忽略 customer，只改数量/日期/备注） */
  editStockout: (id: number, data: StockOutUpdatePayload) =>
    put<{ success?: boolean; message?: string }>(`/stock/out/edit/${id}`, data),
  deleteStockout: (id: number) => del(`/stock/out/delete/${id}`),
  searchProducts: (q: string) => get<{ products?: Product }>('/aux/product-search', { q }),
  availableShipment: (productId: number, customer: string) =>
    get<ApiResponse<ShipmentInfo>>('/aux/available-shipment', { product_id: productId, customer }),
  /**
   * 暂存备货（后端 `staging_stockin.py`）。可用端点：
   * `GET ''`、`POST /import`、`POST /confirm`、`PUT /{id}`、`DELETE /clear`、`DELETE /{id}`。
   *
   * ⚠️ 修正记录（2026-09-18）：`POST /staging-stockins`（无 body 的"新增"）**后端不存在**，
   * 已移除；list 原声明为裸数组，真实响应是 `{success, data, total}`，已纠正。
   */
  stagingStockins: {
    /** 列表查询；`params` 用于分页取全（后端单页上限 500，默认仅 100 条） */
    list: <T = StagingRow>(sessionId?: string, params?: { page?: number; per_page?: number }) =>
      get<StagingListResponse<T>>('/staging-stockins', {
        ...(sessionId ? { session_id: sessionId } : {}),
        ...params,
      }),
    delete: (id: number) => del(`/staging-stockins/${id}`),
    confirm: () => post('/staging-stockins/confirm'),
    clear: () => del('/staging-stockins/clear'),
    importExcel: (formData: FormData) =>
      upload<StagingImportResult>('/staging-stockins/import', formData, undefined, STAGING_IMPORT_TIMEOUT),
  },
  /**
   * 暂存出货（后端 `staging_stockout.py`）。可用端点同上，但 **`session_id` 为必填 Query**：
   * `GET ''?session_id=`、`POST /import?session_id=`、`POST /confirm?session_id=`、
   * `DELETE /clear?session_id=`、`PUT /{id}`、`DELETE /{id}`。
   *
   * ⚠️ 修正记录（2026-09-18）：`POST /staging-stockouts` 不存在（已移除）；
   * `list(sessionId?)` / `clear(sessionId?)` 原为可选参数——不传会被后端判 **422**，
   * 已改为**必填**以在编译期暴露该错误；list 返回类型同步纠正为 `{success, data, total}`。
   */
  stagingStockouts: {
    list: (sessionId: string) =>
      get<StagingListResponse<StagingRow>>('/staging-stockouts', { session_id: sessionId }),
    delete: (id: number) => del(`/staging-stockouts/${id}`),
    confirm: (sessionId: string) =>
      post(`/staging-stockouts/confirm?session_id=${encodeURIComponent(sessionId)}`),
    clear: (sessionId: string) =>
      del(`/staging-stockouts/clear?session_id=${encodeURIComponent(sessionId)}`),
    importExcel: (formData: FormData, sessionId: string) =>
      upload<StagingImportResult>(`/staging-stockouts/import?session_id=${encodeURIComponent(sessionId)}`, formData, undefined, STAGING_IMPORT_TIMEOUT),
  },
  /** 批量提交订单（手工录入的主路径；逐条结果见 `results`） */
  batchSubmitOrders: (orders: Record<string, unknown>[]) =>
    post<BatchSubmitResponse>('/aux/batch-submit-orders', { orders }),
  batchSubmitStockins: (stockins: Record<string, unknown>[]) =>
    post<BatchSubmitResponse>('/aux/batch-submit-stockins', { stockins }),
  batchSubmitStockouts: (stockouts: Record<string, unknown>[]) =>
    post<BatchSubmitResponse>('/aux/batch-submit-stockouts', { stockouts }),
  exportInventory: (params?: QueryParams) => download('/stock/export-inventory', '库存汇总.xlsx', params),
  downloadTemplate: () => download('/batch/download-template', '统一导入模板.xlsx'),
}
