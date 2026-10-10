/** BOM composable 共享类型定义 */

/** BOM 物料类别 */
export type BomCategory = 'fabric' | 'filling' | 'accessory'

/** BOM 角色（一个 SKU 可关联多个角色，每个角色有独立物料清单；角色为**产品私有**） */
export interface Role {
  /** 后端角色 id（新建角色在保存前无 id） */
  id?: number
  /** 新建角色的客户端临时键，保存时经 role_key 归位物料 */
  role_key?: string
  name: string
}

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
  /** 归属角色 id（null = 产品级默认 BOM） */
  role_id?: number | null
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
  role_count: number
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

/** 复制 BOM 的目标角色解析结果 */
export type CopyTargetRole =
  | { ok: true; roleId: number | null; roleName?: string }
  | { ok: false; message: string }

/**
 * 解析「复制 BOM」的归属目标角色。
 *
 * - 未选中角色（默认 BOM 作用域）→ `{ ok: true, roleId: null }`，按源产品结构复制；
 * - 选中已保存角色（有 id）→ `{ ok: true, roleId }`，复制物料归属该角色；
 * - 选中未保存的新角色（无 id，但有名称）→ `{ ok: true, roleId: null, roleName }`，
 *   由后端按角色名查找或新建角色后复制，无需用户先保存；
 * - 无 id 且无名称 → `{ ok: false, message: '请填写角色名称' }`（防御性兜底）。
 *
 * 收敛两处调用（useBomQuickCopy / useBomCopyDialog）的判定逻辑，避免重复。
 *
 * @param selectedRole 当前选中的角色（null 表示默认 BOM 作用域）
 * @returns 解析结果；`ok=false` 时 message 为提示文案
 */
export function resolveCopyTargetRole(selectedRole: Role | null): CopyTargetRole {
  if (!selectedRole) return { ok: true, roleId: null }
  if (selectedRole.id != null) return { ok: true, roleId: selectedRole.id }
  const roleName = (selectedRole.name || '').trim()
  if (!roleName) return { ok: false, message: '请填写角色名称' }
  return { ok: true, roleId: null, roleName }
}

/** `save_bom` 的单个角色负载项。 */
export interface RolePayloadItem {
  /** 既有产品角色关联行 id（改名 / 保持）。 */
  id?: number
  /** 新建角色（客户端临时键）。 */
  role_key?: string
  /** 角色名（产品私有）。 */
  role_name: string
  /** 兼容字段：与 `role_name` 同值，供后端 `role_name || name` 兜底解析。 */
  name?: string
}

/**
 * 构造 `save_bom` 的角色负载，两条互斥路径：
 *
 * - 有 `id` → `{ id, role_name }`（既有产品角色行，按 id 保持物料归属，A-13）；
 * - 否则 → `{ role_key, role_name }`（新建角色，后端按名在本产品内复用/新建）。
 *
 * 纯函数，便于单测直接断言路径。
 *
 * @param roles 当前产品的角色列表
 * @returns 角色负载数组
 */
export function buildRolePayload(roles: Role[]): RolePayloadItem[] {
  return roles.map((role) => {
    const roleName = (role.name || '').trim()
    if (role.id != null) {
      return { id: role.id, role_name: roleName }
    }
    return { role_key: role.role_key, role_name: roleName }
  })
}
