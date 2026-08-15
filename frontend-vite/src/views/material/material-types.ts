// Material 模块共享类型：供应商供货明细（MaterialView / SupplierDialog 共用）

export interface SupMatItem {
  id: number
  ordered: number
  received: number
}

export interface SupMat {
  name: string
  ordered: number
  received: number
  remaining: number
  pct: number
  /** 同物料合并的所有 item 详情（含 id、ordered、received，用于按额度切分收货） */
  subItems: SupMatItem[]
  unit: string
  spec: string
}

export interface SupGroup {
  supplierName: string
  items: SupMat[]
  totalOrdered: number
  totalReceived: number
  pct: number
}

export interface SupplierDetail {
  supplierGroups: SupGroup[]
  totalOrdered: number
  totalReceived: number
  totalPct: number
}
