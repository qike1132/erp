import { get, post, put, del, upload, download } from './request'

export const caseApi = {
  search: (q: string) => get('/cases/search', { q }),
  stockins: (params?: Record<string, unknown>) => get('/cases/in/list', params),
  stockouts: (params?: Record<string, unknown>) => get('/cases/out/list', params),
  batchStockin: (data: Record<string, unknown>) => post('/cases/in/batch', data),
  batchStockout: (data: Record<string, unknown>) => post('/cases/out/batch', data),
  getStockin: (id: number) => get(`/cases/in/${id}`),
  getStockout: (id: number) => get(`/cases/out/${id}`),
  updateStockin: (id: number, data: Record<string, unknown>) => put(`/cases/in/${id}`, data),
  updateStockout: (id: number, data: Record<string, unknown>) => put(`/cases/out/${id}`, data),
  deleteStockin: (id: number) => del(`/cases/in/${id}`),
  deleteStockout: (id: number) => del(`/cases/out/${id}`),
  importStockins: (formData: FormData) => upload('/batch/import-case-stockins', formData),
  importStockouts: (formData: FormData) => upload('/batch/import-case-stockouts', formData),
  downloadTemplate: (filename: string) => download('/batch/download-template', filename),
}
