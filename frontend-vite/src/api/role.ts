/**
 * 全局角色字典客户端（采购中心 `/purchase-center/roles`）。
 *
 * 全局角色是**跨产品复用**的字典项：两产品引用同一角色时落库为**同一**
 * `global_role_id`（A-1）。本模块只负责字典的增删改查；产品与角色的关联
 * 通过 BOM 保存（`global_role_id` 路径）完成，不在此处复制记录。
 *
 * 错误区分（A-14）：
 * - **400** 名称冲突（`lower(trim(name))` 已存在）→ `isRoleNameConflictError`；
 * - **409** 角色被任意产品引用、不可删除 → `isRoleReferencedError`（detail 含引用数）；
 * - **404** 角色不存在。
 *
 * 由于底层 `request.ts` 对 4xx 会 `Promise.reject(AxiosError)`，本模块统一把
 * 错误规整为携带 `status` / `detail` 的 `RoleApiError`，便于调用方分支提示。
 */
import axios from 'axios'
import { get, post, put, del } from './request'

/** 全局角色字典项（`GET /purchase-center/roles` 数组元素）。 */
export interface RoleItem {
  /** 全局角色 id（`role.id`）。 */
  id: number
  /** 角色投影中的关联 id；字典列表里恒为 null（该字段供 BOM 角色投影复用）。 */
  global_role_id: number | null
  /** 角色显示名。 */
  name: string
}

/** 角色接口错误：携带 HTTP 状态码与后端 detail，供调用方区分 400 / 409 / 404。 */
export class RoleApiError extends Error {
  /** HTTP 状态码；网络错误为 0。 */
  readonly status: number
  /** 后端 detail 文案（含被引用计数等）。 */
  readonly detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'RoleApiError'
    this.status = status
    this.detail = detail
  }
}

/**
 * 把任意异常规整为 `RoleApiError`。
 * 导出以便单测直接覆盖 400 / 409 / 网络错误三条分支（无需真实网络）。
 */
export function toRoleApiError(error: unknown): RoleApiError {
  if (axios.isAxiosError(error)) {
    const status = error.response?.status ?? 0
    const payload = error.response?.data as { detail?: unknown } | undefined
    const detail =
      typeof payload?.detail === 'string' && payload.detail
        ? payload.detail
        : error.message || '请求失败'
    return new RoleApiError(status, detail)
  }
  if (error instanceof RoleApiError) return error
  return new RoleApiError(0, error instanceof Error ? error.message : '未知错误')
}

/** 名称冲突（400）。 */
export function isRoleNameConflictError(error: unknown): boolean {
  return error instanceof RoleApiError && error.status === 400
}

/** 角色被引用、不可删除（409）。 */
export function isRoleReferencedError(error: unknown): boolean {
  return error instanceof RoleApiError && error.status === 409
}

const BASE = '/purchase-center/roles'

/** 列出全部全局角色。 */
export async function listRoles(): Promise<RoleItem[]> {
  try {
    const res = await get<{ success: boolean; roles: RoleItem[] }>(BASE)
    return res?.roles ?? []
  } catch (error) {
    throw toRoleApiError(error)
  }
}

/** 新建全局角色；名称冲突抛 `RoleApiError(400)`。 */
export async function createRole(name: string): Promise<RoleItem> {
  try {
    const res = await post<{ success: boolean; role: RoleItem }>(BASE, { name })
    return res.role
  } catch (error) {
    throw toRoleApiError(error)
  }
}

/** 重命名全局角色；冲突抛 `RoleApiError(400)`，不存在抛 `RoleApiError(404)`。 */
export async function renameRole(id: number, name: string): Promise<RoleItem> {
  try {
    const res = await put<{ success: boolean; role: RoleItem }>(`${BASE}/${id}`, { name })
    return res.role
  } catch (error) {
    throw toRoleApiError(error)
  }
}

/** 删除全局角色；被引用抛 `RoleApiError(409)`（detail 含引用数），不存在抛 `(404)`。 */
export async function deleteRole(id: number): Promise<string> {
  try {
    const res = await del<{ success: boolean; message: string }>(`${BASE}/${id}`)
    return res.message || '删除成功'
  } catch (error) {
    throw toRoleApiError(error)
  }
}

/** 角色字典 API 聚合对象（与 `productApi` / `purchaseApi` 风格一致）。 */
export const roleApi = {
  list: listRoles,
  create: createRole,
  rename: renameRole,
  remove: deleteRole,
}
