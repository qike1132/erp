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
  /** 历史关联行的出货单号；按产品退货（P1 起）为空串 */
  stockout_no: string
  reason: string
  note: string
  /** P1-①：active 正常 / cancelled 已取消（软取消保留记录） */
  status: 'active' | 'cancelled' | string
}

/** 创建退货请求体（后端 schemas/stock_return.py::StockReturnCreate） */
export interface StockReturnCreatePayload {
  product_id: number
  quantity: number
  /** 客户名称（可选，自由文本） */
  customer?: string
  /** YYYY-MM-DD；缺省时后端取当天 */
  return_date?: string
  reason?: string
  note?: string
  /** P1-③ 幂等令牌：每次打开弹窗生成；同令牌重复提交后端拒绝 */
  request_id?: string
}

/** 产品名称候选（/stock-returns/product-options） */
export interface NameOption {
  id: number
  name: string
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
  /** 产品名称候选（退货模块自身 manage 门控，勿用 /products/list——那是 product_manage） */
  productOptions: () => get<NameOption[]>('/stock-returns/product-options'),
  create: (data: StockReturnCreatePayload) =>
    post<{ success: boolean; message: string }>('/stock-returns/create', data),
  /** 取消退货（P1-① 软删除：记录保留，库存对称扣回） */
  remove: (id: number) => del<{ success: boolean; message: string }>(`/stock-returns/${id}`),
}
