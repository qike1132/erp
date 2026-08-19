/**
 * useProjectDetail — 打样项目详情面板业务逻辑
 *
 * 封装部位跨版本表格的行内编辑状态、版本筛选（选中/折叠/展开）、
 * 按 part_name 分组与 rowSpan 计算，以及 finalVersion 自动同步。
 */
import { computed, ref, reactive, watch } from 'vue'
import type { ProjectDetailResponse, PartDetail } from '@/api/patternRoom'

export interface ProjectDetailPanelProps {
  project: ProjectDetailResponse | null
  partsByVersion: PartDetail[]
  versionList: string[]
  finalVersion: string
  versionLoading: boolean
  partLoading: boolean
  canManage: boolean
  canPrint: boolean
}

export type ProjectDetailPanelEmit = (
  event: 'set-final-version' | 'save-edit',
  ...args: unknown[]
) => void

/** 分组后的行数据 */
export interface PartGroupRow {
  part_name: string
  rowSpan: number
  items: PartDetail[]
  latestVersionNo: string | null
  collapsed: boolean
  totalVersionCount: number
}

/** 行内编辑表单状态 */
export interface EditFormState {
  supplier_name: string
  fabric_name: string
  fabric_color_no: string
}

export function useProjectDetail(
  props: { partsByVersion: PartDetail[]; finalVersion: string; project: ProjectDetailResponse | null; currentRoleId: number | null },
  emit: ProjectDetailPanelEmit,
) {
  const editingPartId = ref<number | undefined>(undefined)

  const editForm = reactive({
    supplier_name: '',
    fabric_name: '',
    fabric_color_no: '',
  })

  const selectedVersion = ref<Record<string, string | null>>({})
  const expandedParts = ref<Set<string>>(new Set())

  function startEdit(part: PartDetail) {
    if (part.id == null) return
    editingPartId.value = part.id
    editForm.supplier_name = part.supplier_name || ''
    editForm.fabric_name = part.fabric_name || ''
    editForm.fabric_color_no = part.fabric_color_no || ''
  }

  function saveEdit(part: PartDetail) {
    editingPartId.value = undefined
    emit('save-edit', part, { ...editForm })
  }

  function cancelEdit() {
    editingPartId.value = undefined
  }

  watch(
    () => props.partsByVersion,
    () => {
      editingPartId.value = undefined
    },
  )

  watch(
    [() => props.project?.id ?? null, () => props.currentRoleId],
    () => {
      editingPartId.value = undefined
      selectedVersion.value = {}
      expandedParts.value = new Set()
    },
  )

  watch(
    [() => props.finalVersion, () => props.partsByVersion, () => props.project?.id, () => props.currentRoleId],
    ([finalVersion, partsByVersion]) => {
      if (!finalVersion || !props.project) return
      const next: Record<string, string | null> = {}
      for (const item of partsByVersion) {
        if (item.part_name && !next[item.part_name]) {
          if (item.version_no === finalVersion) {
            next[item.part_name] = finalVersion
          }
        }
      }
      selectedVersion.value = next
      expandedParts.value = new Set()
    },
    { immediate: true },
  )

  function toggleVersion(partName: string, versionNo: string) {
    if (selectedVersion.value[partName] === versionNo) {
      const { [partName]: _removed, ...rest } = selectedVersion.value
      void _removed
      selectedVersion.value = rest
      expandedParts.value.delete(partName)
    } else {
      selectedVersion.value = { ...selectedVersion.value, [partName]: versionNo }
      expandedParts.value.delete(partName)
      emit('set-final-version', versionNo)
    }
  }

  function toggleExpand(partName: string) {
    const next = new Set(expandedParts.value)
    if (next.has(partName)) {
      next.delete(partName)
    } else {
      next.add(partName)
    }
    expandedParts.value = next
  }

  const groupedRows = computed<PartGroupRow[]>(() => {
    const items = props.partsByVersion
    const result: PartGroupRow[] = []
    const seen = new Map<string, PartDetail[]>()

    for (const item of items) {
      const key = item.part_name
      if (!seen.has(key)) seen.set(key, [])
      seen.get(key)!.push(item)
    }

    for (const [name, group] of seen) {
      const versionNums = group
        .map((i) => i.version_no)
        .filter(Boolean)
        .map((v) => parseInt((v as string).replace(/^T/i, ''), 10))
        .filter((n) => !isNaN(n))
      const maxNum = versionNums.length > 0 ? Math.max(...versionNums) : null
      const latestVersionNo = maxNum != null ? `T${maxNum}` : null

      const sel = selectedVersion.value[name]
      const versionExists = sel ? group.some((i) => i.version_no === sel) : false
      const shouldFold = Boolean(sel) && versionExists && !expandedParts.value.has(name)
      let filteredItems = shouldFold ? group.filter((i) => i.version_no === sel) : group

      const versionNum = (v?: string | null) => {
        if (!v) return Number.MAX_SAFE_INTEGER
        const n = parseInt(v.replace(/^T/i, ''), 10)
        return isNaN(n) ? Number.MAX_SAFE_INTEGER : n
      }
      filteredItems = [...filteredItems].sort((a, b) => versionNum(a.version_no) - versionNum(b.version_no))

      result.push({
        part_name: name,
        rowSpan: filteredItems.length,
        items: filteredItems,
        latestVersionNo,
        collapsed: shouldFold,
        totalVersionCount: group.length,
      })
    }
    return result
  })

  return {
    editingPartId,
    editForm,
    selectedVersion,
    startEdit,
    saveEdit,
    cancelEdit,
    toggleVersion,
    toggleExpand,
    groupedRows,
  }
}