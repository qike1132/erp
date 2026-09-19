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
} from './purchase'
export { customerApi } from './customer'
export { supplierApi } from './supplier'
export { stockApi } from './stock'
export type { BatchSubmitResponse } from './stock'
export { approvalApi } from './approval'
export { batchApi } from './batch'
export { materialApi } from './material'
export { productionApi, dailyProductionApi } from './production'
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
export { countryApi } from './country'
export { patternRoomApi } from './patternRoom'
export { patternMakerApi } from './patternMaker'

// 向后兼容：productApi 合并核心方法 + BOM 方法（BOM 实际属于采购中心域）
// 新代码应分别使用 productApi（核心）和 bomApi（BOM 相关）
import { productApi as _core } from './product'
import { bomApi } from './purchase'
export const productApi = { ..._core, ...bomApi }
