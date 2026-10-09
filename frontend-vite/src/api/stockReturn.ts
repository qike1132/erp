import { get, post, put, del } from './request'

/** 退货列表行（对应后端 get_stockreturns 的 data 元素） */
export interface StockReturnRecord {
  id: number
  return_no: string
  return_date: string
  product: { id: number; name: string } | null
  quantity: number
  customer: string
  stockout_id: number | null
  /** 历史关联行的出货单号 */
  stockout_no: string
  reason: string
  note: string
  /** active 正常 / cancelled 已取消（历史遗留值，2026-10-09 起取消即硬删除，存量行仍可能有 cancelled） */
  status: 'active' | 'cancelled' | string
}

/** 可退出货明细候选（/stock-returns/shipment-options，按产品名搜索） */
export interface ShipmentOption {
  stockout_id: number
  stockout_no: string
  stockout_date: string
  product_id: number
  product_name: string
  customer: string | null
  quantity: number
  returned_quantity: number
  available: number
}

/** 创建退货请求体（后端 schemas/stock_return.py::StockReturnCreate） */
export interface StockReturnCreatePayload {
  stockout_id: number
  quantity: number
  return_date?: string
  reason?: string
  note?: string
  /** P1-3 幂等令牌：每次打开弹窗生成；同令牌重复提交后端拒绝 */
  request_id?: string
}

/** 编辑退货请求体（后端 schemas/stock_return.py::StockReturnUpdate） */
export interface StockReturnUpdatePayload {
  quantity?: number
  return_date?: string
  reason?: string
  note?: string
}

/** 报表「退货流水」聚合行还原出的明细行（GET /stock-returns/records） */
export interface StockReturnFlowRecord {
  id: number
  return_no: string
  return_date: string
  customer: string
  product_id: number
  product_name: string
  quantity: number
  stockout_id: number | null
  stockout_no: string
  reason: string
  note: string
}

export const stockReturnApi = {
  list: (params?: {
    page?: number
    per_page?: number
    customer?: string
    start_date?: string
    end_date?: string
  }) =>
    get<{ success: boolean; data: StockReturnRecord[]; total: number; page: number; per_page: number }>(
      '/stock-returns/list',
      params,
    ),
  /** 按产品名搜可退出货明细（退货模块自身 manage 门控，勿用 /products/list） */
  shipmentOptions: (q: string) =>
    get<ShipmentOption[]>('/stock-returns/shipment-options', { q }),
  create: (data: StockReturnCreatePayload) =>
    post<{ success: boolean; message: string }>('/stock-returns/create', data),
  /** 报表聚合行还原：按退货单号取明细（供行内编辑/删除） */
  records: (nos: string) =>
    get<{ success?: boolean; data: StockReturnFlowRecord[] }>('/stock-returns/records', { nos }),
  /** 编辑退货（后端单事务内「取消原退货 + 重建」，新记录带新单号） */
  update: (id: number, data: StockReturnUpdatePayload) =>
    put<{ success?: boolean; message?: string }>(`/stock-returns/${id}`, data),
  /** 取消退货（硬删除：记录移除，库存对称扣回；对账以库存流水为准） */
  remove: (id: number) => del<{ success: boolean; message: string }>(`/stock-returns/${id}`),
}
