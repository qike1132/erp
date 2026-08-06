import { get, post, del, upload, download } from './request'
import type {
  Product, StagingOrder, InventoryItem, InventoryResponse, StockInRecord, StockOutRecord,
  ShipmentInfo, ApiResponse, QueryParams,
} from '@/types'

export const stockApi = {
  stats: async () => {
    const resp = await get<{ success: boolean; data: { order_quantity: number; order_regular_quantity: number; order_custom_quantity: number; stockin_quantity: number } }>('/stock/stats');
    return resp.data ?? resp as unknown as typeof resp.data;
  },
  stockins: (params?: QueryParams) => get<StockInRecord[]>('/stock/in/list', params),
  stockouts: (params?: QueryParams) => get<{ stockouts?: StockOutRecord[]; items?: StockOutRecord[]; total?: number }>('/stock/out/list', params),
  inventory: (params?: QueryParams) => get<InventoryResponse>('/stock/inventory', params),
  deleteStockin: (id: number) => del(`/stock/in/delete/${id}`),
  deleteStockout: (id: number) => del(`/stock/out/delete/${id}`),
  searchProducts: (q: string) => get<{ products?: Product }>('/aux/product-search', { q }),
  availableShipment: (productId: number, customer: string, orderType?: string, country?: string) =>
    get<ApiResponse<ShipmentInfo>>('/aux/available-shipment', { product_id: productId, customer, ...(orderType ? { order_type: orderType } : {}), ...(country ? { country } : {}) }),
  stagingStockins: {
    list: () => get<StagingOrder[]>('/staging-stockins'),
    add: (data: Partial<StagingOrder>) => post<StagingOrder>('/staging-stockins', data),
    delete: (id: number) => del(`/staging-stockins/${id}`),
    confirm: () => post('/staging-stockins/confirm'),
    clear: () => del('/staging-stockins/clear'),
    importExcel: (formData: FormData) => upload('/staging-stockins/import', formData),
  },
  stagingStockouts: {
    list: (sessionId?: string) => get<StagingOrder[]>('/staging-stockouts', sessionId ? { session_id: sessionId } : undefined),
    add: (data: Partial<StagingOrder>) => post<StagingOrder>('/staging-stockouts', data),
    delete: (id: number) => del(`/staging-stockouts/${id}`),
    confirm: (sessionId: string) =>
      post(`/staging-stockouts/confirm?session_id=${encodeURIComponent(sessionId)}`),
    clear: (sessionId?: string) =>
      del(`/staging-stockouts/clear${sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ''}`),
    importExcel: (formData: FormData, sessionId: string) =>
      upload<{ success: boolean; message: string; imported: number; errors: string[] }>(`/staging-stockouts/import?session_id=${encodeURIComponent(sessionId)}`, formData),
  },
  batchSubmitStockins: (stockins: Record<string, unknown>[]) => post('/aux/batch-submit-stockins', { stockins }),
  batchSubmitStockouts: (stockouts: Record<string, unknown>[]) => post('/aux/batch-submit-stockouts', { stockouts }),
  exportInventory: (params?: QueryParams) => download('/stock/export-inventory', '库存汇总.xlsx', params),
  downloadTemplate: () => download('/batch/download-template', '统一导入模板.xlsx'),
}
