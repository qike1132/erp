import { get, post, del } from './request'

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
  /** P1-1：active 正常 / cancelled 已取消（软取消保留记录） */
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
  /** 取消退货（P1-1 软删除：记录保留，库存对称扣回） */
  remove: (id: number) => del<{ success: boolean; message: string }>(`/stock-returns/${id}`),
}
