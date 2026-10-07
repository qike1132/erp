/**
 * customer-order 模块局部类型定义
 *
 * OrderItem / StockInRecord 等通用类型从 @/types 复用，
 * 此处仅定义模块内部使用的类型。
 *
 * 2026-10-06 记录查询 tab 收敛至报表页：OrderRecord / OrderDetailData 已迁至
 * views/report/composables/orderRecordTypes.ts（随消费方迁移）；
 * OrderListResponse / StockinListResponse 全仓零引用，一并移除。
 */

/**
 * 单个出货计划批次（2026-10-06 v2 分批版）：
 * 一条订单条目可拆多批，每批独立日期/数量/备注；
 * 各批数量之和必须排满订单数量（用户裁决口径）。
 */
export interface ShipmentPlanSplit {
  /** 出货日期 YYYY-MM-DD */
  date: string
  /** 批次数量 ≥1 */
  quantity: number
  /** 批次备注（落入计划明细 remark） */
  note: string
}

/** 暂存列表项（录入页右栏） */
export interface StagedItem {
  /** 唯一标识，用于异步操作后安全定位（避免索引失效） */
  uid: string
  /**
   * 条目来源：manual = 本页手工新增（仅存在于前端）；
   * import = Excel 批量导入（服务端 staging_* 表是权威副本）；
   * ocr = 粘贴图片识别后人工确认（仅存在于前端）。
   *
   * 服务端导入前会清空当前会话的暂存区，因此重复导入必须用它替换上一次
   * 导入的条目，否则同一批数据会在列表里翻倍（提交时产生重复订单）。
   * ocr 与 manual 都是纯前端条目，不受该替换逻辑影响。
   */
  origin?: 'manual' | 'import' | 'ocr'
  type: 'order' | 'stockin'
  customer: string
  productId: number
  productName: string
  quantity: number
  date: string
  note: string
  deductStock: boolean
  deductQuantity: number
  /**
   * 分批出货计划（仅订单类型有意义）：空数组 = 无计划。
   * Excel/OCR 导入条目默认空，可在暂存编辑弹窗补设。
   */
  shipmentPlans: ShipmentPlanSplit[]
}

/** 录入表单状态 */
export interface FormState {
  type: 'order' | 'stockin'
  date: string
  customer: string
  productSearch: string
  productId: number
  quantity: number
  deductStock: boolean
  deductQuantity: number
  note: string
  /** 分批出货计划：仅订单类型显示与生效（切到备货时保留状态但不参与提交） */
  shipmentPlans: ShipmentPlanSplit[]
}

/**
 * 记录查询 tab 中的统一记录类型已迁出（2026-10-06）：
 * 见 views/report/composables/orderRecordTypes.ts 的 OrderRecord。
 */

/** 产品搜索建议项 */
export interface ProductSuggestion {
  id: number
  value: string
  name: string
  barcode?: string
}

/** 可用备货查询响应中的单项 */
export interface AvailableStockinItem {
  id: number
  quantity: number
  deducted?: number
  available?: number
}

// OCR 粘贴识别的类型已上移为共享定义：@/components/ocr/types（客户订单 / 出货两页共用）
