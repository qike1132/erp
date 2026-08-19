import { computed, ref, watch, type Ref } from 'vue'
import type { PartDetail } from '@/api/patternRoom'

export interface GroupedRow {
  part_name: string
  rowSpan: number
  items: PartDetail[]
  latestVersionNo: string | null
  collapsed: boolean
  totalVersionCount: number
}

export function usePartsVersionFilter(
  partsByVersion: Ref<PartDetail[]>,
  finalVersion: Ref<string>,
  projectId: Ref<number | null | undefined>,
  currentRoleId: Ref<number | null>,
  onSetFinalVersion: (versionNo: string) => void,
) {
  const selectedVersion = ref<Record<string, string | null>>({})
  const expandedParts = ref<Set<string>>(new Set())

  watch(
    [finalVersion, partsByVersion, projectId, currentRoleId],
    ([fv, pbv]) => {
      if (!fv) return
      const next: Record<string, string | null> = {}
      for (const item of pbv) {
        if (item.part_name && !next[item.part_name]) {
          if (item.version_no === fv) {
            next[item.part_name] = fv
          }
        }
      }
      selectedVersion.value = next
      expandedParts.value = new Set()
    },
    { immediate: true },
  )

  watch(
    [projectId, currentRoleId],
    () => {
      selectedVersion.value = {}
      expandedParts.value = new Set()
    },
  )

  function toggleVersion(partName: string, versionNo: string) {
    if (selectedVersion.value[partName] === versionNo) {
      const { [partName]: _, ...rest } = selectedVersion.value
      selectedVersion.value = rest
      expandedParts.value.delete(partName)
    } else {
      selectedVersion.value = { ...selectedVersion.value, [partName]: versionNo }
      expandedParts.value.delete(partName)
      onSetFinalVersion(versionNo)
    }
  }

  function toggleExpand(partName: string) {
    const next = new Set(expandedParts.value)
    if (next.has(partName)) next.delete(partName)
    else next.add(partName)
    expandedParts.value = next
  }

  const groupedRows = computed<GroupedRow[]>(() => {
    const items = partsByVersion.value
    const result: GroupedRow[] = []
    const seen = new Map<string, PartDetail[]>()
    for (const item of items) {
      const key = item.part_name
      if (!seen.has(key)) seen.set(key, [])
      seen.get(key)!.push(item)
    }
    for (const [name, group] of seen) {
      const versionNums = group
        .map(i => i.version_no)
        .filter(Boolean)
        .map(v => parseInt((v as string).replace(/^T/i, ''), 10))
        .filter(n => !isNaN(n))
      const maxNum = versionNums.length > 0 ? Math.max(...versionNums) : null
      const latestVersionNo = maxNum != null ? `T${maxNum}` : null
      const sel = selectedVersion.value[name]
      const versionExists = sel ? group.some(i => i.version_no === sel) : false
      const shouldFold = Boolean(sel) && versionExists && !expandedParts.value.has(name)
      let filteredItems = shouldFold ? group.filter(i => i.version_no === sel) : group
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

  return { selectedVersion, expandedParts, toggleVersion, toggleExpand, groupedRows }
}