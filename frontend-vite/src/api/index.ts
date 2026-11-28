// API Facade - re-exports all API modules for backward compatibility
// 新代码应直接从具体模块导入，如 `import { orderApi } from '@/api/order'`

export { authApi } from './auth'
export { clearCsrfCache } from './request'
export { orderApi } from './order'
export { outsourceApi } from './outsource'
export type {
  OutsourceProcessType,
  OrderOutsourceProcess,
  ProcessTypeListResponse,
  OrderProcessListResponse,
  GenerateProcessResponse,
} from './outsource'
export { bomApi, purchaseApi } from './purchase'
export type {
  MaterialCalcProduct,
  MaterialCalcRow,
  MaterialCalcScopeGroup,
  MaterialCalcResult,
  MaterialOrderInput,
  ProductListResponse as PurchaseProductListResponse,
  SearchSuggestionResponse as PurchaseSearchSuggestionResponse,
  CompletedOrderExportRow,
  CompletedOrderExportResponse,
} from './purchase'
export { customerApi } from './customer'
export { finishedStockApi } from './finishedStock'
export { supplierApi } from './supplier'
export { stockApi } from './stock'
export { stockReturnApi } from './stockReturn'
export type { StockReturnRecord, StockReturnCreatePayload } from './stockReturn'
export type { BatchSubmitResponse } from './stock'
export { batchApi } from './batch'
export { materialApi } from './material'
export { dailyProductionApi } from './production'
export { reportApi } from './report'
export { userApi, permissionApi } from './user'
export { dashboardApi } from './dashboard'
export { ocrApi } from './ocr'
export { planApi } from './plan'
export type {
  StagingErrorItem,
  PlanUploadResult,
  PlanStagingValidateResult,
  PlanStagingConfirmResult,
} from './plan'
export { auxApi } from './auxiliary'
export { backupApi } from './backup'
export { caseApi } from './case'
export { orderBatchApi } from './orderBatch'
export { patternRoomApi } from './patternRoom'
export { patternMakerApi } from './patternMaker'

// 向后兼容：productApi 合并核心方法 + BOM 方法（BOM 实际属于采购中心域）
// 新代码应分别使用 productApi（核心）和 bomApi（BOM 相关）
// L-6 / N-31（2026-11-21 审计）：原 `{ ...core, ...bomApi }` 展开合并遇重名键会
// **静默覆盖**（后者胜出，编译期不报错）；改显式转发，键名冲突时 TS 直接报重复键。
import { productApi as _core } from './product'
import { bomApi } from './purchase'
export const productApi = {
  list: _core.list,
  detail: _core.detail,
  create: _core.create,
  update: _core.update,
  delete: _core.delete,
  search: _core.search,
  bom: _core.bom,
  loadBom: bomApi.loadBom,
  saveBom: bomApi.saveBom,
  searchProductsForBom: bomApi.searchProductsForBom,
  bomPreview: bomApi.bomPreview,
  copyBom: bomApi.copyBom,
}
