/** BOM composable 共享类型定义 */

/** BOM 物料类别 */
export type BomCategory = 'fabric' | 'filling' | 'accessory'

/** BOM 物料项（前端编辑态） */
export interface BomItem {
  id?: number
  name: string
  specification: string
  unit: string
  supplier_id?: number | null
  supplier_name: string
  usage: number
  remark: string
  category?: string
}

/** BOM 搜索结果产品（用于快速复制 / 复制对话框） */
export interface BomSearchProduct {
  id: number
  name: string
  barcode: string
  price: number
  has_bom: boolean
  material_count: number
}

/** BOM 预览统计 */
export interface BomPreviewStats {
  source_name: string
  source_barcode: string
  material_count: number
  fabric_count: number
  filling_count: number
  accessory_count: number
}

/** 进度条状态 */
export interface ProgressState {
  visible: boolean
  percent: number
  text: string
}

/** confirmDialog 接口（与 useConfirmDialog 兼容） */
export interface ConfirmDialogLike {
  confirm: (msg: string, subMsg?: string, dialogType?: 'danger' | 'warning') => Promise<boolean>
}
