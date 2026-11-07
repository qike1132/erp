import type { PartDetail, RoleBrief } from '@/api/patternRoom'
import type { BomItem, Role } from './bomTypes'

export type SamplingImportStatus = 'new' | 'overwrite' | 'conflict'

export interface SamplingImportSourceGroup {
  role: RoleBrief
  parts: PartDetail[]
}

export interface SamplingImportRow {
  key: string
  part: PartDetail
  sourceRoleId: number
  sourceRoleName: string
  status: SamplingImportStatus
  selected: boolean
  quantityPending: true
}

export const SAMPLING_IMPORT_OMITTED_FIELDS = ['unit_price', 'delivery_days', 'contact_person', 'contact_phone'] as const

/** 色号追加到原备注之后；没有色号时原备注逐字保留。 */
export function buildSamplingRemark(part: Pick<PartDetail, 'remark' | 'fabric_color_no'>): string {
  const remark = part.remark?.trim() ?? ''
  const colorNo = part.fabric_color_no?.trim() ?? ''
  return [remark, colorNo ? `色号：${colorNo}` : ''].filter(Boolean).join('；')
}

/** 打样部位只映射为 BOM 面料；数量没有来源，必须为 0 并显式标记待补。 */
export function mapSamplingPartToBom(
  part: PartDetail,
  validSupplierIds: ReadonlySet<number>,
  existing?: BomItem,
): BomItem {
  const supplierId = part.supplier_id != null && validSupplierIds.has(part.supplier_id)
    ? part.supplier_id
    : null
  return {
    id: existing?.id,
    part_name: part.part_name.trim(),
    name: part.fabric_name?.trim() ?? '',
    specification: part.fabric_spec?.trim() ?? '',
    unit: '码',
    supplier_id: supplierId,
    supplier_name: part.supplier_name?.trim() ?? '',
    usage: 0,
    quantity_pending: true,
    remark: buildSamplingRemark(part),
    role_id: existing?.role_id ?? null,
    category: 'fabric',
  }
}

/**
 * 构造预览行。跨角色同名部位优先标为冲突；非冲突行再按目标角色内的
 * part_name 判定覆盖/新增。版本挑选完全由调用方的 final_only 读接口完成。
 */
export function buildSamplingImportRows(
  groups: SamplingImportSourceGroup[],
  targetRoles: Role[],
  getTargetItems: (role: Role) => BomItem[],
): SamplingImportRow[] {
  const partRoleNames = new Map<string, Set<string>>()
  for (const group of groups) {
    for (const part of group.parts) {
      const partName = part.part_name.trim()
      if (!partRoleNames.has(partName)) partRoleNames.set(partName, new Set())
      partRoleNames.get(partName)!.add(group.role.role_name.trim())
    }
  }

  return groups.flatMap((group) => {
    const sourceRoleName = group.role.role_name.trim()
    const targetRole = targetRoles.find((role) => role.name.trim() === sourceRoleName)
    const targetItems = targetRole ? getTargetItems(targetRole) : []
    return group.parts.map((part) => {
      const partName = part.part_name.trim()
      const conflict = (partRoleNames.get(partName)?.size ?? 0) > 1
      const overwrite = targetItems.some((item) => (item.part_name ?? '').trim() === partName)
      return {
        key: `${group.role.id}:${part.id ?? `${part.version_no ?? ''}:${partName}`}`,
        part,
        sourceRoleId: group.role.id,
        sourceRoleName,
        status: conflict ? 'conflict' : overwrite ? 'overwrite' : 'new',
        selected: true,
        quantityPending: true as const,
      }
    })
  })
}
