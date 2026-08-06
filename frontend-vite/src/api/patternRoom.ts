/**
 * 板房模块 API 客户端
 *
 * 对应后端路由前缀: /api/v1/pattern-room
 */
import { get, post, put, del } from './request'
import type { QueryParams } from '@/types'

// ==================== 类型定义 ====================

export interface BomItemVersion {
  id?: number
  bom_item_id?: number
  version: string
  supplier_id?: number | null
  supplier_name: string
  material_spec: string
  unit_price?: number | null
  contact_person: string
  contact_phone: string
  delivery_days?: number | null
  remark: string
  snapshot_at?: string
}

export interface BomItem {
  id?: number
  bom_id?: number
  parent_id?: number | null
  sort_order: number
  material_name: string
  category: 'fabric' | 'filling' | 'accessory' | 'packaging'
  quantity: number
  unit: string
  spec: string
  current_supplier_id?: number | null
  current_supplier_name: string
  current_version: string
  remark: string
  children?: BomItem[]
  versions?: BomItemVersion[]
  // 前端临时字段
  _editing?: boolean
  _expanded?: boolean
}

export interface PatternRoomBom {
  id: number
  bom_no: string
  product_name: string
  customer_id?: number | null
  customer_name: string
  current_version: string
  status: 'draft' | 'sampling' | 'confirmed' | 'archived'
  status_label: string
  remark: string
  created_by?: number | null
  created_by_name?: string | null
  created_at: string
  updated_at: string
  version: number
  items?: BomItem[]
  change_logs?: ChangeLog[]
}

export interface ChangeLog {
  id: number
  bom_id: number
  bom_item_id?: number | null
  change_type: 'create' | 'version_upgrade' | 'supplier_change' | 'status_change' | 'item_edit'
  change_type_label: string
  from_version: string
  to_version: string
  change_reason: string
  change_details: Array<{ field: string; old: unknown; new: unknown }>
  operator_id?: number | null
  operator_name: string
  created_at: string
}

export interface VersionDiff {
  bom_item_id: number
  material_name: string
  category: string
  quantity: number
  unit: string
  from_supplier: string
  to_supplier: string
  diff: Array<{ field: string; old: unknown; new: unknown }>
}

export interface BomListResult {
  success: boolean
  items: PatternRoomBom[]
  total: number
  pages: number
  current_page: number
}

export interface BomDetailResult {
  success: boolean
  bom: PatternRoomBom
}

export interface VersionListResult {
  success: boolean
  versions: string[]
}

export interface VersionCompareResult {
  success: boolean
  from_version: string
  to_version: string
  bom: PatternRoomBom
  differences: VersionDiff[]
}

export interface ChangeLogListResult {
  success: boolean
  items: ChangeLog[]
  total: number
  pages: number
  current_page: number
}

export interface BomActionResult {
  success: boolean
  id?: number
  bom_no?: string
  message?: string
  [key: string]: unknown
}

// ==================== API ====================

export const patternRoomApi = {
  // BOM 管理
  listBom: (params?: QueryParams) =>
    get<BomListResult>('/pattern-room/bom', params),
  getBom: (id: number) =>
    get<BomDetailResult>(`/pattern-room/bom/${id}`),
  createBom: (data: {
    product_name: string
    customer_id?: number | null
    customer_name?: string
    remark?: string
    items?: BomItem[]
  }) => post<BomActionResult>('/pattern-room/bom', data),
  updateBom: (id: number, data: Partial<{
    product_name: string
    customer_id: number | null
    customer_name: string
    remark: string
    status: string
  }>) => put<BomActionResult>(`/pattern-room/bom/${id}`, data),
  deleteBom: (id: number) =>
    del<BomActionResult>(`/pattern-room/bom/${id}`),
  saveBomItems: (id: number, items: BomItem[]) =>
    put<BomActionResult>(`/pattern-room/bom/${id}/items`, { items }),
  copyBom: (id: number, data?: { product_name?: string }) =>
    post<BomActionResult>(`/pattern-room/bom/${id}/copy`, data || {}),

  // 版本管理
  listVersions: (bomId: number) =>
    get<VersionListResult>(`/pattern-room/bom/${bomId}/versions`),
  createVersion: (bomId: number, data: { reason: string }) =>
    post<BomActionResult>(`/pattern-room/bom/${bomId}/versions`, data),
  compareVersions: (bomId: number, from: string, to: string) =>
    get<VersionCompareResult>(`/pattern-room/bom/${bomId}/compare`, { from_version: from, to_version: to }),

  // 变更日志
  listChangeLogs: (bomId: number, params?: QueryParams) =>
    get<ChangeLogListResult>(`/pattern-room/bom/${bomId}/change-logs`, params),
  getChangeLog: (logId: number) =>
    get<{ success: boolean; log: ChangeLog }>(`/pattern-room/change-logs/${logId}`),
}
