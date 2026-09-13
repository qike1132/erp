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
      let group = seen.get(key)
      if (!group) {
        group = []
        seen.set(key, group)
      }
      group.push(item)
    }

    const expanded = expandedParts.value
    const selVer = selectedVersion.value

    for (const [name, group] of seen) {
      // 循环求最大版本号（避免 Math.max(...arr) 大数组栈溢出）
      let maxNum = -1
      for (const item of group) {
        if (item.version_no) {
          const n = parseInt(item.version_no.replace(/^T/i, ''), 10)
          if (!isNaN(n) && n > maxNum) maxNum = n
        }
      }
      const latestVersionNo = maxNum >= 0 ? `T${maxNum}` : null

      const sel = selVer[name]
      const versionExists = sel ? group.some((i) => i.version_no === sel) : false
      const shouldFold = Boolean(sel) && versionExists && !expanded.has(name)
      const filteredItems = shouldFold ? group.filter((i) => i.version_no === sel) : group

      // 排序：按版本号数值升序，无版本号排最后
      const sorted = [...filteredItems].sort((a, b) => {
        const va = a.version_no ? parseInt(a.version_no.replace(/^T/i, ''), 10) : Number.MAX_SAFE_INTEGER
        const vb = b.version_no ? parseInt(b.version_no.replace(/^T/i, ''), 10) : Number.MAX_SAFE_INTEGER
        return (isNaN(va) ? Number.MAX_SAFE_INTEGER : va) - (isNaN(vb) ? Number.MAX_SAFE_INTEGER : vb)
      })

      result.push({
        part_name: name,
        rowSpan: sorted.length,
        items: sorted,
        latestVersionNo,
        collapsed: shouldFold,
        totalVersionCount: group.length,
      })
    }
    return result
  })

  return { selectedVersion, expandedParts, toggleVersion, toggleExpand, groupedRows }
}